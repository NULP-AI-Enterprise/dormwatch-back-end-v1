from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from .models import Complaint
from .serializers import PublicComplaintSerializer
from .similarity_utils import generate_embedding
import numpy as np

class SimilarComplaintsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        text = request.query_params.get('text', '')
        category_id = request.query_params.get('category_id')
        building_id = request.query_params.get('building_id')
        place_id = request.query_params.get('place_id')

        # Require at least some text to search
        if not text or len(text) < 5:
            return Response([])
            
        try:
            emb = generate_embedding(text)
        except Exception:
            return Response([])
            
        if not emb:
            return Response([])

        # Filter complaints from approved to resolved
        queryset = Complaint.objects.filter(
            status__in=['approved', 'in_progress', 'review', 'resolved'],
            archived=False,
            embedding__isnull=False
        )
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if place_id:
            queryset = queryset.filter(place_id=place_id)
        elif building_id:
            queryset = queryset.filter(
                Q(place__building_id=building_id) | Q(user__building_id=building_id)
            )

        # Get top 3 most similar in memory
        target_emb = np.array(emb)
        scored_complaints = []
        for complaint in queryset:
            if not complaint.embedding:
                continue
            db_emb = np.array(complaint.embedding)
            # Cosine similarity: (A dot B) / (norm(A) * norm(B))
            # Cosine distance: 1 - cosine similarity
            if np.linalg.norm(db_emb) == 0 or np.linalg.norm(target_emb) == 0:
                continue
            cos_sim = np.dot(target_emb, db_emb) / (np.linalg.norm(target_emb) * np.linalg.norm(db_emb))
            cos_dist = 1 - cos_sim
            scored_complaints.append((cos_dist, complaint))

        # Sort by distance (smaller is better) and take top 3
        scored_complaints.sort(key=lambda x: x[0])
        similar_complaints = [c for score, c in scored_complaints[:3] if score < 0.5] # Add threshold so unrelated things aren't returned

        serializer = PublicComplaintSerializer(similar_complaints, many=True)
        return Response(serializer.data)


class UpvoteComplaintView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id, *args, **kwargs):
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
            if request.user.profile not in complaint.supporters.all():
                complaint.supporters.add(request.user.profile)
            return Response({'status': 'success'})
        except Complaint.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
