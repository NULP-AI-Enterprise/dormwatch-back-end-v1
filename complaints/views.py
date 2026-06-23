from django.shortcuts import render
from django.db.models import F
from rest_framework import generics, permissions, viewsets
from rest_framework.parsers import MultiPartParser, FormParser

from .models import Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory, ComplaintVote, Role, Ticket
from .serializers import ComplaintSerializer, UpdateUserRoleSerializer, ComplaintStatusSerializer, CommentSerializer, UpdateUserSerializer, UserSerializer, UpdateUserPlaceSerializer, TicketSerializer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from .permissions import IsCustomAdmin, IsAdminOrCustomAdmin, IsAdminUser
from rest_framework import status


# Create your views here.

class ComplaintView(APIView):
    '''THIS VIEW IS FOR ADMIN AND OTHERS TO SEE'''
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        complaints = Complaint.objects.all()
        category_param = request.query_params.get('category')
        status_param = request.query_params.get('status')
        corps_param = request.query_params.get('corps')
        if category_param:
            complaints = complaints.filter(category_id=category_param)
        if status_param:
            complaints = complaints.filter(status=status_param)
        if corps_param:
            complaints = complaints.filter(user__place__building__name=corps_param)
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
        if not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
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
        category_name = request.data.get('category')
        category_obj = None
        target_place = None

        if place_id:
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
            serializer.save(user=user_profile, place=target_place, category=category_obj)
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

    # def put(self, request, complaint_id):
    #     user_profile = UserProfile.objects.filter(user=request.user).first()
    #     if not user_profile:
    #         return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
    #     try:
    #         complaint = Complaint.objects.get(complaint_id=complaint_id, user=user_profile)
    #     except Complaint.DoesNotExist:
    #         return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
    #     serializer = ComplaintSerializer(complaint, data=request.data)
    #     if serializer.is_valid():
    #         serializer.save()
    #         return Response(serializer.data, status=status.HTTP_200_OK)
    #     return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, user=user_profile)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)

        complaint.delete()
        return Response({'status': 'Deleted succesfully'}, status=status.HTTP_204_NO_CONTENT)

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
    
    # def patch(self, request):
    #     try:
    #         user_profile = (
    #             UserProfile.objects
    #             .select_related("place__building")
    #             .get(user=request.user)
    #         )
    #     except UserProfile.DoesNotExist:
    #         return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
    #     except AttributeError:
    #         return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        
    #     serializer = UpdateUserSerializer(user_profile, data=request.data, partial=True)
    #     if serializer.is_valid():
    #         serializer.save()
    #         user_profile.refresh_from_db()
    #         serializer = UserSerializer(user_profile)
    #         return Response(serializer.data, status=status.HTTP_200_OK)
    #     return Response(serializer.errors, status = status.HTTP_400_BAD_REQUEST)    
    
    def delete(self, request):
        user=request.user
        user.delete()
        return Response({'status': 'Deleted successfully'},status=status.HTTP_204_NO_CONTENT)

class AdminComplaintStatusView(APIView):
    permission_classes = [IsAdminOrCustomAdmin]

    def patch(self, request, complaint_id):
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = ComplaintStatusSerializer(
            complaint,
            data = request.data,
            partial = True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status = status.HTTP_200_OK)

        return Response(serializer.errors, status = status.HTTP_400_BAD_REQUEST)    


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
        return Response({'status': 'Deleted successfully'},status=status.HTTP_204_NO_CONTENT)


class ComplaintVoteView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
       
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
            if ComplaintVote.objects.filter(user=user_profile, complaint=complaint).exists():
                return Response(
                    {'error': 'You have already voted'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            ComplaintVote.objects.create(user=user_profile, complaint=complaint)
            
            votes_count = ComplaintVote.objects.filter(complaint=complaint).count()
            return Response({'votes': votes_count}, status=status.HTTP_200_OK)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)

class TicketView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.role or user_profile.role.role_name.lower() not in ['admin', 'адміністратор']:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        tickets = Ticket.objects.all()
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
        else:
            return Response(
                {"error": "complaint_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if worker_id:
            try:
                target_worker=UserProfile.objects.get(user_id=worker_id)
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
    parser_classes = [MultiPartParser, FormParser]
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
