from django.shortcuts import render
from django.db.models import F
from rest_framework import generics, permissions, viewsets
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from django.db import IntegrityError
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory, Role, Ticket, Notification
from .serializers import ComplaintSerializer, UpdateUserRoleSerializer, ComplaintStatusSerializer, CommentSerializer, UpdateUserSerializer, UserSerializer, UpdateUserPlaceSerializer, TicketSerializer, NotificationSerializer, CategorySerializer, DormitoryBuildingSerializer, PlaceSerializer
from .image_utils import process_complaint_photo
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from .permissions import IsCustomAdmin, IsAdminOrCustomAdmin, IsAdminUser
from rest_framework import status


# Create your views here.

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
        duty_master_phone = (request.data.get('duty_master_phone') or '').strip()
        building = DormitoryBuilding.objects.create(
            name=name,
            address=address,
            commandant_phone=commandant_phone,
            duty_master_phone=duty_master_phone,
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
    '''THIS VIEW IS FOR ADMIN AND OTHERS TO SEE'''
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        is_admin = user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор']
        
        complaints = Complaint.objects.all()
        if not is_admin:
            # Public board shows both live and completed issues: 'published'
            # (active) and 'resolved' (fixed). 'pending'/'denied' stay hidden.
            complaints = complaints.filter(status__in=['published', 'resolved'])
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
        serializer = ComplaintSerializer(complaints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ComplaintDetailView(APIView):
    '''THIS VIEW IS FOR ADMIN AND OTHERS TO SEE ONE COMPLAINT'''
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request,complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        is_admin = user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор']
        
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
            
        if not is_admin and complaint.status not in ['published', 'resolved'] and complaint.user != user_profile:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        serializer = ComplaintSerializer(complaint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserComplaintView(APIView):
    '''THIS VIEW IS FOR USER TO CREATE AND SEE ALL OF THEIR COMPLAINTS'''
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request):
        try:
            user_profile = request.user.profile
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        complaints = Complaint.objects.filter(user=user_profile)
        serializer = ComplaintSerializer(complaints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        place_id = request.data.get('place_id')
        place_name = request.data.get('place_name')
        category_name = request.data.get('category')
        category_obj = None
        target_place = None

        if place_name:
            building = None
            if user_profile.place and user_profile.place.building:
                building = user_profile.place.building
            else:
                building = DormitoryBuilding.objects.first()
            if building:
                target_place, _ = Place.objects.get_or_create(
                    building=building,
                    place_name=place_name
                )
                if not user_profile.place:
                    user_profile.place = target_place
                    user_profile.save()
        elif place_id:
            try:
                target_place = Place.objects.get(place_id=place_id)
            except Place.DoesNotExist:
                return Response({'error': 'Place not found.'}, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                return Response({'error': f'Cannot find the place: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        elif user_profile.place:
            target_place = user_profile.place

        if category_name:
            category_obj, _ = ComplaintCategory.objects.get_or_create(name=category_name)
        else:
            return Response(
                {'error': 'Category name is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        data = request.data.copy()
        serializer = ComplaintSerializer(data=data)
        if serializer.is_valid():
            complaint = serializer.save(user=user_profile, place=target_place, category=category_obj)
            try:
                admins = UserProfile.objects.filter(role__role_name__in=['admin', 'адміністратор'])
                priority_labels = {
                    'low': 'низьким',
                    'medium': 'середнім',
                    'high': 'високим',
                    'critical': 'критичним'
                }
                priority_label = priority_labels.get(complaint.priority, complaint.priority)
                title = f"Нова скарга: {complaint.title}"
                message = f"З'явилася скарга з {priority_label} пріоритетом: {complaint.title}"
                for admin in admins:
                    Notification.objects.create(
                        user=admin,
                        title=title,
                        message=message,
                        complaint=complaint
                    )
            except Exception as e:
                print("Error creating admin notification:", e)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
        complaint.priority = request.data.get('priority', complaint.priority)

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
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
            
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
            
        if complaint.status in ['resolved', 'denied']:
            return Response({'error': 'Cannot delete a resolved or denied complaint'}, status=status.HTTP_403_FORBIDDEN)
            
        is_admin = user_profile.role and user_profile.role.role_name.lower() in ['admin', 'адміністратор']
        
        if complaint.user != user_profile and not is_admin:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

        if is_admin and complaint.user != user_profile:
            try:
                title = f"Видалення скарги: {complaint.title}"
                message = f"Адмін видалив твою скаргу: '{complaint.title}'"
                Notification.objects.create(
                    user=complaint.user,
                    title=title,
                    message=message,
                    complaint=None
                )
            except Exception as e:
                print("Error creating delete notification:", e)

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

class AdminComplaintStatusView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request, complaint_id):
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
            
        if complaint.status in ['resolved', 'denied']:
            return Response({'error': 'Cannot edit a resolved or denied complaint'}, status=status.HTTP_403_FORBIDDEN)
        old_status = complaint.status

        serializer = ComplaintStatusSerializer(
            complaint,
            data=request.data,
            partial=True
        )

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        for field in ['status', 'priority', 'title', 'description']:
            if field in serializer.validated_data:
                setattr(complaint, field, serializer.validated_data[field])

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

        if old_status != complaint.status:
            try:
                status_labels = {
                    'pending': 'На розгляді',
                    'published': 'Опубліковано',
                    'denied': 'Відхилено',
                    'resolved': 'Вирішено'
                }
                status_label = status_labels.get(complaint.status, complaint.status)
                Notification.objects.create(
                    user=complaint.user,
                    title=f"Оновлення статусу: {complaint.title}",
                    message=f"Статус скарги змінено на: {status_label}",
                    complaint=complaint
                )
            except Exception as e:
                print("Error creating status change notification:", e)

        result_serializer = ComplaintSerializer(complaint)
        return Response(result_serializer.data, status=status.HTTP_200_OK)    


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


class TicketView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    def get(self,request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        tickets = Ticket.objects.all()
        date_from_param = request.query_params.get('date_from')
        date_to_param = request.query_params.get('date_to')
        worker_param = request.query_params.get('worker')
        priority_param = request.query_params.get('priority')
        if worker_param:
            tickets = tickets.filter(user_id=worker_param)
        if priority_param:
            tickets = tickets.filter(complaint__priority=priority_param)
        if date_from_param:
            tickets = tickets.filter(deadline__gte=date_from_param)
        if date_to_param:
            tickets = tickets.filter(deadline__lte=date_to_param)
        serializer = TicketSerializer(tickets, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)
    def post(self,request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        complaint_id = request.data.get('complaint')
        worker_id = request.data.get('user')
        target_complaint = None
        target_worker = None

        if complaint_id:
            try:
                target_complaint = Complaint.objects.get(complaint_id=complaint_id)
            except Complaint.DoesNotExist:
                return Response({'error': 'Complaint not found.'}, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                return Response({'error': f'Cannot find the complaint: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
                
            if target_complaint.status != 'published':
                return Response({'error': 'Can only create tickets for published complaints'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(
                {"error": "complaint_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if worker_id:
            try:
                target_worker=UserProfile.objects.get(user_id=worker_id)
                if not target_worker.role or target_worker.role.role_name.lower() != 'worker':
                    return Response({'error': 'User is not a worker'}, status=status.HTTP_400_BAD_REQUEST)
            except UserProfile.DoesNotExist:
                return Response({'error': 'Worker not found'}, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                return Response({'error': f'Cannot find the worker: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        data = request.data.copy()
        serializer = TicketSerializer(data=data)
        if serializer.is_valid():
            serializer.save(complaint=target_complaint, user=target_worker)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class TicketDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    def get(self, request, ticket_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        try:
            ticket = Ticket.objects.get(ticket_id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({'error': 'Ticket not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = TicketSerializer(ticket)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, ticket_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile or not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            ticket = Ticket.objects.get(ticket_id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({'error': 'Ticket not found'}, status=status.HTTP_404_NOT_FOUND)
        
        worker_id = request.data.get('user')
        if worker_id is not None:
            if worker_id == "":
                ticket.user = None
            else:
                try:
                    target_worker = UserProfile.objects.get(user_id=worker_id)
                    if not target_worker.role or target_worker.role.role_name.lower() != 'worker':
                        return Response({'error': 'User is not a worker'}, status=status.HTTP_400_BAD_REQUEST)
                    ticket.user = target_worker
                except UserProfile.DoesNotExist:
                    return Response({'error': 'Worker not found'}, status=status.HTTP_404_NOT_FOUND)
        
        deadline = request.data.get('deadline')
        if deadline is not None:
            if deadline == "":
                ticket.deadline = None
            else:
                ticket.deadline = deadline
            
        ticket.save()
        serializer = TicketSerializer(ticket)
        return Response(serializer.data, status=status.HTTP_200_OK)

class EmployeeListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile or not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
            
        # Return all users who could be assigned as workers
        employees = UserProfile.objects.filter(role__role_name__iexact='worker')
        serializer = UserSerializer(employees, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserTicketView(APIView):
    '''Read-only: the tickets (work orders) opened for THIS resident's own
    complaints. Residents never assign/schedule — that stays admin-only in
    TicketView — but they can see who is handling their request and by when.'''
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user_profile = request.user.profile
        except (UserProfile.DoesNotExist, AttributeError):
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        # select_related('user') avoids an N+1: TicketSerializer nests the
        # assigned worker profile. order_by gives the client a deterministic
        # order when a complaint has more than one ticket.
        tickets = (
            Ticket.objects
            .filter(complaint__user=user_profile)
            .select_related('user')
            .order_by('ticket_id')
        )
        serializer = TicketSerializer(tickets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_profile = getattr(request.user, 'profile', None)
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
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


class ChangeUserRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        building_id = request.data.get('building_number')
        room_number = request.data.get('room_number')
        
        if not building_id or not room_number:
            return Response({'error': 'building_number and room_number are required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            building = DormitoryBuilding.objects.get(building_id=building_id)
        except DormitoryBuilding.DoesNotExist:
            return Response({'error': 'Building not found.'}, status=status.HTTP_404_NOT_FOUND)
            
        place, _ = Place.objects.get_or_create(
            building=building,
            place_name=room_number
        )
        
        user_profile.place = place
        user_profile.save()
        
        return Response({'detail': 'Room updated successfully'}, status=status.HTTP_200_OK)

