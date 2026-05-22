from django.shortcuts import render
from django.db.models import F
from rest_framework import generics, permissions, viewsets
from rest_framework.parsers import MultiPartParser, FormParser

from .models import Complaint, UserProfile, Comment, DormitoryBuilding, DormitoryFloor, DormitoryRoom, ComplaintCategory, ComplaintVote
from .serializers import  ComplaintSerializer, UpdateAdminStatusSerializer, ComplaintStatusSerializer, CommentSerializer, UpdateUserSerializer, UserSerializer, UpdateUserRoomSerializer, ComplaintCountSerializer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from .permissions import IsCustomAdmin, IsAdminOrCustomAdmin, IsAdminUser
from rest_framework import status


# Create your views here.
class ComplaintView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.is_admin:
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
            complaints = complaints.filter(user__room__floor__building__number=corps_param)
        serializer = ComplaintSerializer(complaints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ComplaintDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def get(self,request,complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user_profile.is_admin:
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ComplaintSerializer(complaint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserComplaintView(APIView):
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
        building_num = request.data.get('building_number') 
        floor_num = request.data.get('floor_number')       
        room_num = request.data.get('room_number')
        category_num = request.data.get('room')         
        category_obj = None
        target_room = None
        if building_num and floor_num and room_num:
            try:
                building = DormitoryBuilding.objects.get(number=building_num)
                floor, _ = DormitoryFloor.objects.get_or_create(
                    building=building,
                    floor_number=floor_num
                )
                target_room, _ = DormitoryRoom.objects.get_or_create(
                    floor=floor,
                    room_number=room_num
                )

            except DormitoryBuilding.DoesNotExist:
                return Response(
                    {'error': f'Building "{building_num}" not found.'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                return Response({'error': f'Can`t find the room: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)


        elif user_profile.room:
            target_room = user_profile.room

        if category_num:
            category_obj, _ = ComplaintCategory.objects.get_or_create(name=category_num)
        else:
            return Response(
                {'error': 'Category name is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )


        data = request.data.copy()
        serializer = ComplaintSerializer(data=data)
        if serializer.is_valid():
            serializer.save(user=user_profile, room = target_room, category = category_obj)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserComplaintDetailView(APIView):
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

    def put(self, request, complaint_id):
        user_profile = UserProfile.objects.filter(user=request.user).first()
        if not user_profile:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id, user=user_profile)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ComplaintSerializer(complaint, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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

class UpdateUserStatusView(APIView):
    permission_classes = [IsAdminUser]
    def patch(self, request, user_id):
        try:
            user_profile = UserProfile.objects.get(user = user_id)
        except UserProfile.DoesNotExist:
            return Response({'error': 'User not found'}, status = status.HTTP_404_NOT_FOUND)
        
        serializer = UpdateAdminStatusSerializer(
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
                .select_related("room__floor__building")
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
                .select_related("room__floor__building")
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
            serializer.save(user=user_profile, complaint_id=complaint_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    
    def get(self, request, complaint_id):
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)
        
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
        
        if comment.user != user_profile and not user_profile.is_admin:
            return Response({'error': 'Permission denied'},status=status.HTTP_403_FORBIDDEN)

        comment.delete()
        return Response({'status': 'Deleted successfully'},status=status.HTTP_204_NO_CONTENT)


class UpdateUserRoomView(APIView):
    permission_classes=[IsAuthenticated]
    def patch(self, request):
        try:
            user_profile = (
                UserProfile.objects.get(user=request.user)
            )
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = UpdateUserRoomSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        building_number = serializer.validated_data['building_number']
        floor_number = serializer.validated_data['floor_number']
        room_number = serializer.validated_data['room_number']
        try:
            building = DormitoryBuilding.objects.get(number=building_number)
        except DormitoryBuilding.DoesNotExist:
            return Response(
                {'error': 'Building not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            floor = DormitoryFloor.objects.get(
                building=building,
                floor_number=floor_number
            )
        except DormitoryFloor.DoesNotExist:
            return Response(
                {'error': 'Floor not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            room, created = DormitoryRoom.objects.get_or_create(
                floor=floor,
                room_number=room_number
            )
        except DormitoryRoom.DoesNotExist:
            return Response(
                {'error': 'Room not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        user_profile.room = room
        user_profile.save()

        return Response(
            {'status': 'Room updated successfully'},
            status=status.HTTP_200_OK
        )


class ComplaintCounterView(APIView):
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
            complaint.counter = F('counter') + 1
            complaint.save(update_fields=['counter'])
            complaint.refresh_from_db()
            serializer = ComplaintCountSerializer(complaint)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Complaint.DoesNotExist:
            return Response({'error': 'Complaint not found'}, status=status.HTTP_404_NOT_FOUND)