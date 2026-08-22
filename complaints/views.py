from datetime import timedelta

from django.shortcuts import render
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import generics, permissions, viewsets
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from django.db import IntegrityError
from .models import (
    Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory,
    Role, Notification, PendingTransitionNotice, Worker, Announcement,
)
from .serializers import (
    ComplaintSerializer, ComplaintCreateSerializer, PublicComplaintSerializer,
    AdminComplaintDetailSerializer, AdminComplaintUpdateSerializer,
    WorkerComplaintSerializer, WorkerStampSerializer,
    UpdateUserRoleSerializer, CommentSerializer, UpdateUserSerializer,
    UserSerializer, NotificationSerializer, CategorySerializer,
    DormitoryBuildingSerializer, PlaceSerializer, WorkerSerializer,
    AdminUpdateUserSerializer, RoleSerializer, AnnouncementSerializer,
)
from .image_utils import process_complaint_photo
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from .permissions import IsCustomAdmin, IsAdminOrCustomAdmin, IsAdminUser
from rest_framework import status


# Transition matrix: actor × from-state legality. Endpoints validate against
# this before touching the model; the model's `transition()` is the single
# place that writes status + timestamps together.
ADMIN_TRANSITIONS = {
    'pending': {'approved', 'rejected'},
    'approved': {'in_progress', 'rejected'},
    'in_progress': {'approved', 'review', 'rejected'},
    'review': {'in_progress', 'resolved'},
}
# Undo moves for stamps are admin-only backwards steps inside the matrix above;
# workers get their own narrow set.
WORKER_TRANSITIONS = {
    'start': ('approved', 'in_progress', 'started'),
    'finish': ('in_progress', 'review', 'finished'),
    'start_undo': ('in_progress', 'approved', 'started_undo'),
    'finish_undo': ('review', 'in_progress', 'finished_undo'),
}
RESIDENT_TRANSITIONS = {
    'accept': ('review', 'resolved'),
    'reject': ('review', 'not_accepted'),
    'withdraw': ('pending', 'withdrawn'),
}

# Admin proxy stamps land in the event log with the admin as actor — that
# provenance is what keeps pay disputes and step09 reports honest.
ADMIN_STATUS_EVENTS = {
    ('approved', 'in_progress'): 'started',
    ('in_progress', 'review'): 'finished',
    ('in_progress', 'approved'): 'started_undo',
    ('review', 'in_progress'): 'finished_undo',
}

# States a complaint can be re-filed from: only closed ones. An open source is
# still being worked; its remedy is the lifecycle, not a second complaint.
TERMINAL_STATUSES = {'resolved', 'rejected', 'not_accepted', 'withdrawn'}

# How long a staged transition notification waits before materializing — the
# worker panel's undo window (step 07). Swept lazily at notification read time.
TRANSITION_UNDO_WINDOW = timedelta(seconds=30)

STATUS_LABELS = {
    'pending': 'Очікує',
    'approved': 'Схвалено',
    'in_progress': 'В роботі',
    'review': 'На перевірці',
    'resolved': 'Вирішено',
    'rejected': 'Відхилено',
    'not_accepted': 'Не прийнято',
    'withdrawn': 'Скасовано',
}


def _get_profile(request):
    return UserProfile.objects.filter(user=request.user).first()


def _is_admin(user_profile):
    return bool(user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор'])


def _admin_profiles():
    return UserProfile.objects.filter(role__role_name__in=['admin', 'адміністратор'])


def _stage_transition_notices(complaint, actor=None):
    '''Stage who hears about this transition, replacing anything staged before:
    an undo inside the window overwrites/deletes the pending row instead of
    letting a stale ping through. Routing (split): the owning resident hears
    about every progress move; admins hear only about rejections and resident
    rejections of completed work — never routine progress taps.'''
    PendingTransitionNotice.objects.filter(complaint=complaint).delete()

    rows = []
    ready_at = timezone.now() + TRANSITION_UNDO_WINDOW
    label = STATUS_LABELS.get(complaint.status, complaint.status)
    title = f"Оновлення статусу: {complaint.title}"

    def stage(recipient, message):
        if recipient and recipient != actor and not any(r[0] == recipient for r in rows):
            rows.append((recipient, message))

    if complaint.status == 'rejected':
        reason = complaint.rejection_reason or ''
        suffix = f" Причина: {reason}" if reason else ''
        stage(complaint.user, f"Звернення «{complaint.title}» відхилено.{suffix}")
        for admin in _admin_profiles():
            stage(admin, f"Звернення «{complaint.title}» відхилено адміністратором.")
    elif complaint.status == 'not_accepted':
        reason = complaint.rework_reason or ''
        suffix = f" Причина: {reason}" if reason else ''
        for admin in _admin_profiles():
            stage(admin, f"Мешканець не прийняв виконану роботу за «{complaint.title}».{suffix}")
    elif complaint.status == 'withdrawn':
        pass  # the owner withdrew it themselves; nobody else is pinged
    else:
        messages = {
            'pending': f"Статус звернення «{complaint.title}»: {label}",
            'approved': f"Звернення «{complaint.title}» схвалено та передано в роботу.",
            'in_progress': f"Роботи за «{complaint.title}» почато.",
            'review': f"Роботи за «{complaint.title}» виконано — на перевірці.",
            'resolved': f"Звернення «{complaint.title}» вирішено.",
        }
        msg = messages.get(complaint.status)
        if msg:
            stage(complaint.user, msg)

    PendingTransitionNotice.objects.bulk_create([
        PendingTransitionNotice(
            complaint=complaint, recipient=recipient, title=title,
            message=message, ready_at=ready_at,
        )
        for recipient, message in rows
    ])


def _sweep_transition_notices():
    '''Materialize staged transition notices whose undo window has passed into
    real notifications. Called lazily at the top of the notifications list
    endpoint (no scheduler in this project).'''
    due = list(PendingTransitionNotice.objects.filter(ready_at__lte=timezone.now()))
    if not due:
        return
    Notification.objects.bulk_create([
        Notification(
            user=n.recipient, title=n.title, message=n.message, complaint=n.complaint,
        )
        for n in due
    ])
    PendingTransitionNotice.objects.filter(notice_id__in=[n.notice_id for n in due]).delete()


def _notify_worker_accounts(worker_ids, title, message, complaint):
    '''Assignment routing: notify the linked account of each affected worker
    (account-less workers work from paper and hear nothing in-app).'''
    profiles = UserProfile.objects.filter(worker__worker_id__in=worker_ids)
    for profile in profiles:
        Notification.objects.create(user=profile, title=title, message=message, complaint=complaint)


def _apply_assignment_change(complaint, new_worker, actor):
    '''Write assignment changes with honest per-worker attribution: append the
    event (assigned/unassigned/reassigned) and notify the dropped/new worker
    accounts. Returns nothing; caller persists via save().'''
    old_worker = complaint.worker
    complaint.worker = new_worker
    if old_worker == new_worker:
        return
    if new_worker and not old_worker:
        complaint.log_event('assigned', actor=actor)
        _notify_worker_accounts(
            [new_worker.worker_id],
            "Нове завдання",
            f"Вам призначено звернення «{complaint.title}».",
            complaint,
        )
    elif old_worker and not new_worker:
        complaint.log_event('unassigned', actor=actor)
        _notify_worker_accounts(
            [old_worker.worker_id],
            "Завдання знято",
            f"Вас знято зі звернення «{complaint.title}».",
            complaint,
        )
    elif old_worker and new_worker:
        complaint.log_event('reassigned', actor=actor)
        _notify_worker_accounts(
            [old_worker.worker_id],
            "Завдання знято",
            f"Вас знято зі звернення «{complaint.title}».",
            complaint,
        )
        _notify_worker_accounts(
            [new_worker.worker_id],
            "Нове завдання",
            f"Вам призначено звернення «{complaint.title}».",
            complaint,
        )


# Create your views here.

def _allowed_complaint_places(user_profile):
    '''The bounded set of places a resident may file a звернення against: their
    own assigned room (UserProfile.place) plus every shared room
    (kitchen/laundry/common) in their building. Shared rooms are complaint
    locations only and are exempt from any capacity notion. Building is the
    first-class profile field; fall back to the room's building for residents
    whose building is only known via their place (mirrors the web app's own
    `building ?? place.building` fallback). Returns Place objects, own room
    first, then shared rooms by name, de-duplicated.'''
    building = user_profile.building
    if building is None and user_profile.place:
        building = user_profile.place.building

    places = []
    seen = set()
    if user_profile.place:
        places.append(user_profile.place)
        seen.add(user_profile.place.place_id)
    if building:
        shared = Place.objects.filter(
            is_shared=True, building=building
        ).order_by('place_name')
        for p in shared:
            if p.place_id not in seen:
                places.append(p)
                seen.add(p.place_id)
    return places


class CategoryListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        categories = ComplaintCategory.objects.all()
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)


class AdminCategoryCreateView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Name is required'}, status=status.HTTP_400_BAD_REQUEST)
        category, created = ComplaintCategory.objects.get_or_create(name=name)
        if not created:
            return Response({'error': 'Category with this name already exists'}, status=status.HTTP_409_CONFLICT)
        serializer = CategorySerializer(category)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AdminCategoryDetailView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, category_id):
        try:
            category = ComplaintCategory.objects.get(category_id=category_id)
        except ComplaintCategory.DoesNotExist:
            return Response({'error': 'Category not found'}, status=status.HTTP_404_NOT_FOUND)
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'error': 'Name is required'}, status=status.HTTP_400_BAD_REQUEST)
        if ComplaintCategory.objects.filter(name=name).exclude(category_id=category_id).exists():
            return Response({'error': 'Category with this name already exists'}, status=status.HTTP_409_CONFLICT)
        category.name = name
        category.save()
        return Response(CategorySerializer(category).data, status=status.HTTP_200_OK)

    def delete(self, request, category_id):
        try:
            category = ComplaintCategory.objects.get(category_id=category_id)
        except ComplaintCategory.DoesNotExist:
            return Response({'error': 'Category not found'}, status=status.HTTP_404_NOT_FOUND)
        # Non-destructive: category is SET_NULL, so complaints survive detached.
        detached = Complaint.objects.filter(category=category).count()
        category.delete()
        return Response({'detached_complaints': detached}, status=status.HTTP_200_OK)


class AdminBuildingCreateView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        address = (request.data.get('address') or '').strip()
        if not name or not address:
            return Response({'error': 'Name and address are required'}, status=status.HTTP_400_BAD_REQUEST)
        commandant_phone = (request.data.get('commandant_phone') or '').strip()
        building = DormitoryBuilding.objects.create(
            name=name,
            address=address,
            commandant_phone=commandant_phone,
        )
        return Response(DormitoryBuildingSerializer(building).data, status=status.HTTP_201_CREATED)


class AdminBuildingDetailView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, building_id):
        try:
            building = DormitoryBuilding.objects.get(building_id=building_id)
        except DormitoryBuilding.DoesNotExist:
            return Response({'error': 'Building not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = DormitoryBuildingSerializer(building, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, building_id):
        try:
            building = DormitoryBuilding.objects.get(building_id=building_id)
        except DormitoryBuilding.DoesNotExist:
            return Response({'error': 'Building not found'}, status=status.HTTP_404_NOT_FOUND)
        places_count = Place.objects.filter(building=building).count()
        force = request.query_params.get('force') == 'true'
        if places_count and not force:
            return Response(
                {'error': 'Building has rooms; remove them first', 'places_count': places_count},
                status=status.HTTP_409_CONFLICT,
            )
        building.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminPlaceDetailView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, place_id):
        try:
            place = Place.objects.get(place_id=place_id)
        except Place.DoesNotExist:
            return Response({'error': 'Place not found'}, status=status.HTTP_404_NOT_FOUND)
        place_name = (request.data.get('place_name') or '').strip()
        if not place_name:
            return Response({'error': 'place_name is required'}, status=status.HTTP_400_BAD_REQUEST)
        place.place_name = place_name
        # capacity / is_shared are optional on a PATCH; apply only when present.
        if 'capacity' in request.data:
            place.capacity = request.data.get('capacity') or 0
        if 'is_shared' in request.data:
            place.is_shared = bool(request.data.get('is_shared'))
        try:
            place.save()
        except IntegrityError:
            return Response({'error': 'A room with this name already exists in the building'}, status=status.HTTP_409_CONFLICT)
        return Response(PlaceSerializer(place).data, status=status.HTTP_200_OK)

    def delete(self, request, place_id):
        try:
            place = Place.objects.get(place_id=place_id)
        except Place.DoesNotExist:
            return Response({'error': 'Place not found'}, status=status.HTTP_404_NOT_FOUND)
        # Non-destructive: complaint.place is SET_NULL, so complaints survive detached.
        detached = Complaint.objects.filter(place=place).count()
        place.delete()
        return Response({'detached_complaints': detached}, status=status.HTTP_200_OK)


class ComplaintView(APIView):
    '''Board feed. Admins read every live complaint in full; everyone else gets
    the building-scoped public board — approved + resolved only, anonymized
    (no room, no photo, no author identity).'''
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request):
        user_profile = _get_profile(request)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        is_admin = _is_admin(user_profile)

        complaints = Complaint.objects.filter(archived=False).select_related('category', 'place__building', 'user', 'worker')
        if is_admin:
            serializer_class = ComplaintSerializer
        else:
            complaints = complaints.filter(
                status__in=['approved', 'resolved'],
                place__building=user_profile.building,
            )
            serializer_class = PublicComplaintSerializer
        category_param = request.query_params.get('category')
        status_param = request.query_params.get('status')
        corps_param = request.query_params.get('corps')
        priority_param = request.query_params.get('priority')
        if category_param:
            complaints = complaints.filter(category_id=category_param)
        if status_param:
            complaints = complaints.filter(status=status_param)
        if corps_param:
            complaints = complaints.filter(user__place__building__name=corps_param)
        if priority_param:
            complaints = complaints.filter(priority=priority_param)
        serializer = serializer_class(complaints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ComplaintDetailView(APIView):
    '''One complaint, scoped by role: admins get the full record, the owner the
    full record of their own, an assigned worker the job-context slice, and
    anyone else the anonymized public view (approved/resolved only).'''
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request,complaint_id):
        user_profile = _get_profile(request)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        is_admin = _is_admin(user_profile)

        try:
            complaint = Complaint.objects.select_related('category', 'place__building', 'user', 'worker').get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)

        if is_admin:
            serializer = AdminComplaintDetailSerializer(complaint)
        elif complaint.user == user_profile:
            serializer = ComplaintSerializer(complaint)
        elif complaint.worker and complaint.worker.account == user_profile:
            serializer = WorkerComplaintSerializer(complaint)
        elif complaint.status in ['approved', 'resolved'] and not complaint.archived:
            serializer = PublicComplaintSerializer(complaint)
        else:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserComplaintView(APIView):
    '''THIS VIEW IS FOR USER TO CREATE AND SEE ALL OF THEIR COMPLAINTS'''
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request):
        try:
            user_profile = request.user.profile
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        complaints = Complaint.objects.filter(user=user_profile, archived=False)
        serializer = ComplaintSerializer(complaints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        place_id = request.data.get('place_id')
        category_name = request.data.get('category')
        category_obj = None
        target_place = None

        # A resident may only file against their OWN room or a shared room in
        # their building — never an arbitrary room, and never a newly invented
        # one (no implicit get_or_create). place_name (free-text create) is no
        # longer accepted here.
        if place_id:
            allowed = {p.place_id for p in _allowed_complaint_places(user_profile)}
            try:
                place_id_int = int(place_id)
            except (TypeError, ValueError):
                return Response(
                    {'place': 'Можна обрати лише власну або спільну кімнату'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if place_id_int not in allowed:
                return Response(
                    {'place': 'Можна обрати лише власну або спільну кімнату'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            target_place = Place.objects.get(place_id=place_id_int)
        elif user_profile.place:
            target_place = user_profile.place

        if category_name:
            category_obj, _ = ComplaintCategory.objects.get_or_create(name=category_name)
        else:
            return Response(
                {'error': 'Category name is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Resident payload whitelist: title/description/photo only. Status,
        # priority, and assignment are never resident-writable.
        serializer = ComplaintCreateSerializer(data=request.data)
        if serializer.is_valid():
            complaint = serializer.save(
                user=user_profile, place=target_place,
                category=category_obj, status='pending', priority='medium',
            )
            try:
                for admin in _admin_profiles():
                    Notification.objects.create(
                        user=admin,
                        title=f"Нова скарга: {complaint.title}",
                        message=f"З'явилася нова скарга: {complaint.title}",
                        complaint=complaint
                    )
            except Exception as e:
                print("Error creating admin notification:", e)
            return Response(ComplaintSerializer(complaint).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MyComplaintPlacesView(APIView):
    '''The bounded set of rooms the requesting resident may file a звернення
    against: their own assigned room + all shared rooms in their building.
    Feeds the constrained room selector on the create-report page so the client
    can only offer allowed options (server still re-validates on POST).'''
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        places = _allowed_complaint_places(user_profile)
        serializer = PlaceSerializer(places, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserComplaintDetailView(APIView):
    '''THIS VIEW IS FOR USER TO SEE ONE COMPLAINT AND ABILITY DELETE IT'''
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    def get(self, request, complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, user=user_profile)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ComplaintSerializer(complaint)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, user=user_profile)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        if complaint.status != 'pending':
            return Response({'error': 'Can only edit pending complaints'}, status=status.HTTP_403_FORBIDDEN)

        complaint.title = request.data.get('title', complaint.title)
        complaint.description = request.data.get('description', complaint.description)

        category_name = request.data.get('category_name')
        if category_name:
            try:
                category_obj = ComplaintCategory.objects.get(name=category_name)
            except ComplaintCategory.DoesNotExist:
                return Response({'error': f'Category "{category_name}" not found'}, status=status.HTTP_400_BAD_REQUEST)
            complaint.category = category_obj

        photo_file = request.FILES.get('photo_url')
        if photo_file:
            if photo_file.size > 10 * 1024 * 1024:
                return Response({'error': 'File size must be under 10MB'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            result = process_complaint_photo(photo_file)
            complaint.photo_url = result['full']
            complaint.thumbnail = result['thumbnail']

        complaint.save()
        serializer = ComplaintSerializer(complaint)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, complaint_id):
        '''Owner-side removal. While Очікує (and nothing is assigned yet) the
        owner may hard-delete their own complaint; afterwards the lifecycle
        belongs to the process — withdraw/accept paths own the outcome.'''
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, user=user_profile)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)

        if complaint.status != 'pending' or complaint.worker:
            return Response(
                {'error': 'Скасувати можна лише звернення, що ще очікує на розгляд'},
                status=status.HTTP_403_FORBIDDEN,
            )

        complaint.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class UpdateUserRoleView(APIView):
    permission_classes = [IsAdminUser]
    def patch(self, request, user_id):
        try:
            user_profile = UserProfile.objects.get(user = user_id)
        except UserProfile.DoesNotExist:
            return Response({'error': 'User not found'}, status = status.HTTP_404_NOT_FOUND)
        
        serializer = UpdateUserRoleSerializer(
            user_profile,
            data = request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status = status.HTTP_200_OK)

        return Response(serializer.errors, status = status.HTTP_400_BAD_REQUEST)


class RoleListView(APIView):
    '''Assignable roles for the admin residents page (edit dialog + role filter).
    Returns the full role table, not just roles currently in use.'''
    permission_classes = [IsAdminOrCustomAdmin]

    def get(self, request):
        roles = Role.objects.all().order_by('role_name')
        serializer = RoleSerializer(roles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminUserListView(APIView):
    '''Admin residents roster. select_related avoids N+1 on the nested
    building/place/role that UserSerializer renders.'''
    permission_classes = [IsAdminOrCustomAdmin]

    def get(self, request):
        profiles = (
            UserProfile.objects
            .select_related('role', 'building', 'place__building')
            .order_by('first_name', 'last_name')
        )
        serializer = UserSerializer(profiles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminUserDetailView(APIView):
    '''Admin edit of a resident's dorm building / room / role.'''
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, user_id):
        try:
            user_profile = UserProfile.objects.get(user=user_id)
        except UserProfile.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        # No self-demotion: an admin may fix their own building/room, but not
        # change their own role (would let the last admin lock everyone out).
        if str(user_id) == str(request.user.id) and 'role_id' in request.data:
            return Response(
                {'error': 'Cannot change your own role'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AdminUpdateUserSerializer(user_profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            user_profile.refresh_from_db()
            return Response(UserSerializer(user_profile).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(APIView):
    permission_classes=[IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    def get(self, request):
        try:
            user_profile = (
                UserProfile.objects
                .select_related("place__building")
                .get(user=request.user)
            )
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        
        serializer = UserSerializer(user_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def patch(self, request):
        try:
            user_profile = (
                UserProfile.objects
                .select_related("place__building")
                .get(user=request.user)
            )
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        
        serializer = UpdateUserSerializer(user_profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            user_profile.refresh_from_db()
            serializer = UserSerializer(user_profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status = status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request):
        user=request.user
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class AdminComplaintDetailView(APIView):
    '''The single admin surface over a complaint's assignment + lifecycle.
    Replaces the old ticket endpoints and status endpoint: one GET (full
    record incl. event log), one PATCH (assignment, deadline, triage moves,
    proxy stamps for account-less workers, finalize, rejection), one DELETE
    (hard-delete before assignment, archive afterwards).'''
    permission_classes = [IsAdminOrCustomAdmin]

    def get(self, request, complaint_id):
        try:
            complaint = Complaint.objects.select_related(
                'category', 'place__building', 'user', 'worker'
            ).prefetch_related('events__actor').get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(AdminComplaintDetailSerializer(complaint).data, status=status.HTTP_200_OK)

    def patch(self, request, complaint_id):
        actor = _get_profile(request)
        if not actor:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        if complaint.archived:
            return Response(
                {'error': 'Архівоване звернення доступне лише для читання'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = AdminComplaintUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        # --- Resolve the target state of every touched dimension first, so
        # legality checks see the combined result, then apply. ---
        current_status = complaint.status
        target_status = data.get('status', current_status)
        worker_changed = 'worker_id' in data

        if target_status != current_status:
            legal = ADMIN_TRANSITIONS.get(current_status, set())
            if target_status not in legal:
                return Response(
                    {'status': f'Неприпустимий перехід: {STATUS_LABELS.get(current_status, current_status)} → {STATUS_LABELS.get(target_status, target_status)}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Assignment legality: work happens after approval — pending carries no
        # worker unless the same request approves it.
        new_worker = complaint.worker
        if worker_changed:
            if data['worker_id'] is None:
                new_worker = None
            else:
                try:
                    new_worker = Worker.objects.get(worker_id=data['worker_id'])
                except Worker.DoesNotExist:
                    return Response({'worker_id': 'Працівника не знайдено'}, status=status.HTTP_400_BAD_REQUEST)
            final_status_needs_worker = target_status in ('approved', 'in_progress', 'review')
            if new_worker and target_status == 'pending':
                return Response(
                    {'worker_id': 'Призначення можливе лише після схвалення'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not new_worker and final_status_needs_worker:
                return Response(
                    {'worker_id': f'Для статусу «{STATUS_LABELS[target_status]}» потрібен призначений працівник'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Proxy stamps for account-less workers: entering in_progress/review
        # requires someone to be assigned to do the work.
        if target_status in ('in_progress', 'review') and not new_worker:
            return Response(
                {'status': 'Для цього статусу потрібен призначений працівник'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Admin rejection is terminal and must say why.
        if target_status == 'rejected' and not (data.get('rejection_reason') or '').strip() and not complaint.rejection_reason:
            return Response(
                {'rejection_reason': 'Вкажіть причину відхилення'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Apply: plain fields first, then assignment events, then the
        # lifecycle transition (the single writer of status + timestamps). ---
        if 'deadline' in data:
            complaint.deadline = data['deadline']
        if 'priority' in data:
            complaint.priority = data['priority']
        if 'rejection_reason' in data:
            complaint.rejection_reason = data['rejection_reason']

        status_changed = target_status != current_status
        if worker_changed:
            _apply_assignment_change(complaint, new_worker, actor)

        if status_changed:
            # Persist plain-field edits together with the transition write.
            complaint.save()
            complaint.transition(target_status)
            event_action = ADMIN_STATUS_EVENTS.get((current_status, target_status))
            if event_action:
                complaint.log_event(event_action, actor=actor)
            _stage_transition_notices(complaint, actor=actor)
        else:
            complaint.save()

        complaint.refresh_from_db()
        return Response(AdminComplaintDetailSerializer(complaint).data, status=status.HTTP_200_OK)

    def delete(self, request, complaint_id):
        '''State-aware deletion. Before a worker is assigned: hard delete
        (confirmed client-side). Afterwards: archive — hidden from lists and
        feeds, retained for reports and pay disputes; rejection marks and
        follow-up chains survive.'''
        actor = _get_profile(request)
        if not actor:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)

        if complaint.worker is None:
            complaint.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        complaint.archived = True
        complaint.archived_by = actor
        complaint.archived_at = timezone.now()
        complaint.save(update_fields=['archived', 'archived_by', 'archived_at'])
        complaint.log_event('archived', actor=actor)
        return Response(
            AdminComplaintDetailSerializer(complaint).data,
            status=status.HTTP_200_OK,
        )


class ResidentComplaintActionView(APIView):
    '''Owner-only lifecycle verbs: accept (→ Вирішено) and reject with a
    required reason (→ terminal Не прийнято) once work is on review, withdraw
    while Очікує. Legality comes from RESIDENT_TRANSITIONS — nothing here can
    be spoofed by payload shape.'''
    permission_classes = [IsAuthenticated]
    action = None  # bound per-route via as_view(action=...)

    def post(self, request, complaint_id):
        action = self.action
        actor = _get_profile(request)
        if not actor:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, user=actor)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        if complaint.archived:
            return Response({'error': 'Звернення архівовано'}, status=status.HTTP_403_FORBIDDEN)

        spec = RESIDENT_TRANSITIONS.get(action)
        if spec is None:
            return Response({'error': 'Unknown action'}, status=status.HTTP_404_NOT_FOUND)
        from_state, to_state = spec

        if complaint.status != from_state:
            return Response(
                {'status': f'Дія доступна лише для статусу «{STATUS_LABELS[from_state]}»'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action == 'reject':
            reason = (request.data.get('rework_reason') or '').strip()
            if not reason:
                return Response(
                    {'rework_reason': 'Опишіть, що саме не прийнято'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            complaint.rework_reason = reason

        complaint.transition(to_state)
        _stage_transition_notices(complaint, actor=actor)
        return Response(ComplaintSerializer(complaint).data, status=status.HTTP_200_OK)


class ComplaintRefileView(APIView):
    '''Re-file: the owner creates a fresh complaint out of a closed one. A
    creating verb, hence POST. The server allows at most one OPEN follow-up
    per source (partial unique constraint), so a double-tap cannot duplicate
    even under concurrent submits.'''
    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id):
        actor = _get_profile(request)
        if not actor:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            source = Complaint.objects.get(complaint_id=complaint_id, user=actor)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        if source.archived:
            return Response({'error': 'Звернення архівовано'}, status=status.HTTP_403_FORBIDDEN)

        if source.status not in TERMINAL_STATUSES:
            return Response(
                {'status': 'Повторне звернення можна подати лише по завершеному'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        description = (request.data.get('description') or '').strip() or source.description
        try:
            follow_up = Complaint.objects.create(
                user=actor,
                place=source.place,
                title=source.title,
                description=description,
                category=source.category,
                follow_up_of=source,
                root=source.root or source,
            )
        except IntegrityError:
            # The partial unique constraint caught a concurrent/double submit:
            # this source already has one open follow-up.
            return Response(
                {'follow_up_of': 'Відкрите повторне звернення за цим зверненням уже існує'},
                status=status.HTTP_409_CONFLICT,
            )
        # Admins hear about follow-up filings immediately (nothing undoable).
        try:
            for admin in _admin_profiles():
                Notification.objects.create(
                    user=admin,
                    title=f"Повторне звернення: {follow_up.title}",
                    message=f"Мешканець повторно подав звернення (джерело №{source.complaint_id}): {follow_up.title}",
                    complaint=follow_up,
                )
        except Exception as e:
            print("Error creating refile notifications:", e)
        return Response(ComplaintSerializer(follow_up).data, status=status.HTTP_201_CREATED)


class WorkerComplaintListView(APIView):
    '''Account-holding workers read their own job list: assigned, live, scoped
    to job context only (no resident identity, no dorm-wide feed).'''
    permission_classes = [IsAuthenticated]

    def get(self, request):
        actor = _get_profile(request)
        if not actor:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        worker = getattr(actor, 'worker', None)
        if worker is None:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        complaints = (
            Complaint.objects
            .filter(worker=worker, archived=False)
            .exclude(status__in=TERMINAL_STATUSES)
            .select_related('category', 'place__building')
            .order_by('deadline')
        )
        serializer = WorkerComplaintSerializer(complaints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkerComplaintActionView(APIView):
    '''Account-holder stamps: Взято в роботу / Виконано (+ undos), optional
    note — restricted to THIS worker's assigned complaints. Stamps go through
    the single transition helper so timestamps stay consistent.'''
    permission_classes = [IsAuthenticated]

    def patch(self, request, complaint_id):
        actor = _get_profile(request)
        if not actor:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        worker = getattr(actor, 'worker', None)
        if worker is None:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, worker=worker)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        if complaint.archived:
            return Response({'error': 'Звернення архівовано'}, status=status.HTTP_403_FORBIDDEN)

        serializer = WorkerStampSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        action = serializer.validated_data['action']
        from_state, to_state, event_action = WORKER_TRANSITIONS[action]

        if complaint.status != from_state:
            return Response(
                {'status': f'Дія доступна лише для статусу «{STATUS_LABELS[from_state]}»'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if 'note' in serializer.validated_data:
            complaint.work_note = serializer.validated_data['note']
            complaint.save(update_fields=['work_note'])

        complaint.transition(to_state)
        complaint.log_event(event_action, actor=actor)
        _stage_transition_notices(complaint, actor=actor)
        return Response(WorkerComplaintSerializer(complaint).data, status=status.HTTP_200_OK)


class CommentListView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, complaint_id):
       
        user_profile = UserProfile.objects.filter( user = request.user).first()

        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        

        serializer = CommentSerializer(data=request.data)
        if serializer.is_valid():
            is_admin = user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор']
            if complaint.user != user_profile and not is_admin:
                return Response({'error': 'Permission denied'},status=status.HTTP_403_FORBIDDEN)
            serializer.save(user=user_profile, complaint_id=complaint_id)
            
            if is_admin and complaint.user != user_profile:
                try:
                    Notification.objects.create(
                        user=complaint.user,
                        title="Новий коментар адміністратора",
                        message=f"Адміністратор {user_profile.first_name} {user_profile.last_name} прокоментував вашу скаргу: {complaint.title}",
                        complaint=complaint
                    )
                except Exception as e:
                    print("Failed to create comment notification:", e)
                    
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    
    def get(self, request, complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        is_admin = user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор']
        if complaint.user != user_profile and not is_admin:
            return Response({'error': 'Permission denied'},status=status.HTTP_403_FORBIDDEN)
        comments =( Comment.objects
                   .filter(complaint_id=complaint_id)
                   .select_related("user")
                   .order_by("created_at")
                   )
        
        serializer = CommentSerializer(comments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class CommentDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    def delete(self, request, comment_id):
       
        user_profile = UserProfile.objects.filter(user = request.user).first()
        
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            comment = Comment.objects.get(comment_id=comment_id)
        except Comment.DoesNotExist:
            return Response(
                {'error': 'Comment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        is_admin = user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор']
        if comment.user != user_profile and not is_admin:
            return Response({'error': 'Permission denied'},status=status.HTTP_403_FORBIDDEN)

        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkerListCreateView(APIView):
    '''Admin-managed roster of external contractors. GET also serves the
    complaint assignment dropdown.'''
    permission_classes = [IsAdminOrCustomAdmin]

    def get(self, request):
        workers = Worker.objects.all().order_by('full_name')
        serializer = WorkerSerializer(workers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = WorkerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WorkerDetailView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, worker_id):
        try:
            worker = Worker.objects.get(worker_id=worker_id)
        except Worker.DoesNotExist:
            return Response({'error': 'Worker not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = WorkerSerializer(worker, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, worker_id):
        try:
            worker = Worker.objects.get(worker_id=worker_id)
        except Worker.DoesNotExist:
            return Response({'error': 'Worker not found'}, status=status.HTTP_404_NOT_FOUND)
        # SET_NULL on Complaint.worker unassigns any complaints rather than
        # deleting them.
        worker.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompletedReportView(APIView):
    '''Admin report of completed work: resolved complaints with an assigned
    worker, filtered by resolved_at within [date_from, date_to] (inclusive on
    both bounds by calendar day). One row per complaint: title, resolved_at,
    building + room, category, and the assigned worker + deadline. Archived
    rows stay in — the report is exactly where archived history remains
    readable.'''
    permission_classes = [IsAdminOrCustomAdmin]

    def get(self, request):
        date_from_param = request.query_params.get('date_from')
        date_to_param = request.query_params.get('date_to')

        complaints = (
            Complaint.objects
            .filter(status='resolved', worker__isnull=False)
            .select_related('category', 'place__building', 'worker')
            .order_by('-resolved_at')
        )
        if date_from_param:
            complaints = complaints.filter(resolved_at__date__gte=date_from_param)
        if date_to_param:
            complaints = complaints.filter(resolved_at__date__lte=date_to_param)

        rows = []
        for complaint in complaints:
            place = complaint.place
            worker = complaint.worker
            rows.append({
                'complaint_id': complaint.complaint_id,
                'title': complaint.title,
                'resolved_at': complaint.resolved_at,
                'building': place.building.name if place and place.building else None,
                'room': place.place_name if place else None,
                'category': complaint.category.name if complaint.category else None,
                'priority': complaint.priority,
                'worker': {
                    'worker_id': worker.worker_id,
                    'full_name': worker.full_name,
                    'company': worker.company,
                    'phone': worker.phone,
                } if worker else None,
                'deadline': complaint.deadline,
            })

        return Response(rows, status=status.HTTP_200_OK)


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_profile = getattr(request.user, 'profile', None)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        # Materialize transition notices whose undo window has passed before
        # reading (announcements-style lazy sweep — no scheduler).
        _sweep_transition_notices()
        notifications = Notification.objects.filter(user=user_profile).order_by('-created_at')[:50]
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        user_profile = getattr(request.user, 'profile', None)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            notification = Notification.objects.get(notification_id=notification_id, user=user_profile)
        except Notification.DoesNotExist:
            return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)
        
        notification.is_read = True
        notification.save()
        serializer = NotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_profile = getattr(request.user, 'profile', None)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        Notification.objects.filter(user=user_profile, is_read=False).update(is_read=True)
        return Response({'status': 'all notifications marked as read'}, status=status.HTTP_200_OK)


def _sweep_expired_pins():
    '''Clear is_pinned on any announcement whose expiry has passed. There is no
    task scheduler in this project, so this "unpin on expiry" rule is enforced
    lazily — called at the top of every announcement list endpoint.'''
    Announcement.objects.filter(
        expires_at__lt=timezone.localdate(), is_pinned=True
    ).update(is_pinned=False)


def _parse_expires_at(raw):
    '''Parse an expires_at request value. Returns (date|None, error). A falsy
    value (None / '' / false) clears the expiry; anything else must be an
    ISO YYYY-MM-DD date.'''
    if not raw:
        return None, None
    parsed = parse_date(raw) if isinstance(raw, str) else None
    if parsed is None:
        return None, 'Invalid expires_at (expected YYYY-MM-DD)'
    return parsed, None


class AdminAnnouncementView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def get(self, request):
        _sweep_expired_pins()
        announcements = (Announcement.objects
                         .select_related('building', 'created_by')
                         .order_by('-is_pinned', '-created_at'))
        serializer = AnnouncementSerializer(announcements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        title = (request.data.get('title') or '').strip()
        body = (request.data.get('body') or '').strip()
        if not title or not body:
            return Response({'error': 'Title and body are required'}, status=status.HTTP_400_BAD_REQUEST)

        building = None
        building_id = request.data.get('building')
        if building_id:
            try:
                building = DormitoryBuilding.objects.get(building_id=building_id)
            except DormitoryBuilding.DoesNotExist:
                return Response({'error': 'Building not found'}, status=status.HTTP_404_NOT_FOUND)

        expires_at, err = _parse_expires_at(request.data.get('expires_at'))
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)

        author = getattr(request.user, 'profile', None)
        announcement = Announcement.objects.create(
            title=title,
            body=body,
            building=building,
            is_pinned=bool(request.data.get('is_pinned')),
            expires_at=expires_at,
            created_by=author,
        )

        # Fan out in-app Notification rows so the existing bell surfaces the post.
        # Global → all residents; building-scoped → that building's residents.
        # Use bulk_create (unlike the per-row complaint idiom) since this can hit
        # every resident.
        try:
            residents = UserProfile.objects.exclude(role__role_name__in=['admin', 'адміністратор'])
            if building is not None:
                # A resident's building may be null yet known via their place's
                # building (see _allowed_complaint_places) — union both sets.
                ids = set(UserProfile.objects.filter(building=building).values_list('user_id', flat=True))
                ids |= set(UserProfile.objects
                           .filter(building__isnull=True, place__building=building)
                           .values_list('user_id', flat=True))
                residents = residents.filter(user_id__in=ids)
            notif_title = f"Оголошення: {announcement.title}"
            objs = [
                Notification(user=r, title=notif_title, message=announcement.body, complaint=None)
                for r in residents.iterator()
            ]
            Notification.objects.bulk_create(objs, batch_size=500)
        except Exception as e:
            print("Error creating announcement notifications:", e)

        return Response(AnnouncementSerializer(announcement).data, status=status.HTTP_201_CREATED)


class AdminAnnouncementDetailView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, announcement_id):
        try:
            announcement = Announcement.objects.get(announcement_id=announcement_id)
        except Announcement.DoesNotExist:
            return Response({'error': 'Announcement not found'}, status=status.HTTP_404_NOT_FOUND)

        if 'title' in request.data:
            title = (request.data.get('title') or '').strip()
            if not title:
                return Response({'error': 'Title cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
            announcement.title = title
        if 'body' in request.data:
            body = (request.data.get('body') or '').strip()
            if not body:
                return Response({'error': 'Body cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
            announcement.body = body
        if 'building' in request.data:
            building_id = request.data.get('building')
            if building_id:
                try:
                    announcement.building = DormitoryBuilding.objects.get(building_id=building_id)
                except DormitoryBuilding.DoesNotExist:
                    return Response({'error': 'Building not found'}, status=status.HTTP_404_NOT_FOUND)
            else:
                announcement.building = None
        if 'is_pinned' in request.data:
            announcement.is_pinned = bool(request.data.get('is_pinned'))
        if 'expires_at' in request.data:
            expires_at, err = _parse_expires_at(request.data.get('expires_at'))
            if err:
                return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
            announcement.expires_at = expires_at

        announcement.save()
        # Editing does NOT re-fan-out notifications (avoids spamming residents on
        # every tweak); only creation pushes.
        return Response(AnnouncementSerializer(announcement).data, status=status.HTTP_200_OK)

    def delete(self, request, announcement_id):
        try:
            announcement = Announcement.objects.get(announcement_id=announcement_id)
        except Announcement.DoesNotExist:
            return Response({'error': 'Announcement not found'}, status=status.HTTP_404_NOT_FOUND)
        # Already-sent Notification rows are independent records and are retained.
        announcement.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AnnouncementListView(APIView):
    '''Resident feed + dashboard widget source: global + own-building notices.'''
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _sweep_expired_pins()
        user_profile = getattr(request.user, 'profile', None)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        building = user_profile.building or (user_profile.place.building if user_profile.place else None)
        announcements = Announcement.objects.select_related('building', 'created_by')
        if building is not None:
            announcements = announcements.filter(Q(building__isnull=True) | Q(building=building))
        else:
            announcements = announcements.filter(building__isnull=True)
        # Expired posts stay reachable (client de-emphasizes; widget filters them).
        announcements = announcements.order_by('-is_pinned', '-created_at')
        serializer = AnnouncementSerializer(announcements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

