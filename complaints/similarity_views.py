import re
import numpy as np
from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from .models import Complaint, Place
from .serializers import PublicComplaintSerializer
from .similarity_utils import generate_embedding

class SimilarComplaintsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        text = (request.query_params.get('text') or '').strip()
        category_id = request.query_params.get('category_id')
        building_id = request.query_params.get('building_id')
        place_id = request.query_params.get('place_id')

        # Extract search keywords (>= 3 chars)
        words = [w.lower() for w in re.findall(r'\w+', text) if len(w) >= 3]

        # Require at least one meaningful word (>= 3 chars) or text length >= 4
        if not text or (len(text) < 4 and len(words) == 0):
            return Response([])

        # Filter complaints: active open complaints only (exclude resolved, rejected, withdrawn)
        queryset = Complaint.objects.filter(
            status__in=['pending', 'approved', 'in_progress', 'review'],
            archived=False
        )

        if category_id:
            try:
                queryset = queryset.filter(category_id=int(category_id))
            except (ValueError, TypeError):
                pass

        if place_id:
            try:
                p_id = int(place_id)
                place_obj = Place.objects.filter(place_id=p_id).select_related('building').first()
                b_id = place_obj.building_id if place_obj else building_id
                if b_id:
                    # Match complaints for the exact place OR shared places in the same building
                    queryset = queryset.filter(
                        Q(place_id=p_id) | Q(place__is_shared=True, place__building_id=b_id)
                    )
                else:
                    queryset = queryset.filter(place_id=p_id)
            except (ValueError, TypeError):
                pass
        elif building_id:
            try:
                b_id = int(building_id)
                queryset = queryset.filter(
                    Q(place__building_id=b_id) | Q(user__building_id=b_id)
                )
            except (ValueError, TypeError):
                pass
        else:
            user_profile = getattr(request.user, 'profile', None)
            if user_profile and user_profile.building_id:
                queryset = queryset.filter(
                    Q(place__building_id=user_profile.building_id) |
                    Q(user__building_id=user_profile.building_id)
                )

        target_emb = None
        try:
            raw_emb = generate_embedding(text)
            if raw_emb:
                target_emb = np.array(raw_emb)
        except Exception as e:
            print(f"Error generating embedding for similarity search: {e}")

        scored_complaints = []
        for complaint in queryset:
            c_title = (complaint.title or '').lower()
            c_desc = (complaint.description or '').lower()
            combined_text = f"{c_title} {c_desc}"

            # Check keyword match in title vs description
            title_match = any(w in c_title for w in words) if words else False
            desc_match = any(w in combined_text for w in words) if words else False
            has_keyword_match = title_match or desc_match

            score = 1.0  # default distance
            if target_emb is not None and complaint.embedding:
                db_emb = np.array(complaint.embedding)
                norm_target = np.linalg.norm(target_emb)
                norm_db = np.linalg.norm(db_emb)
                if norm_target > 0 and norm_db > 0:
                    cos_sim = np.dot(target_emb, db_emb) / (norm_target * norm_db)
                    score = 1.0 - float(cos_sim)

            # Strong boost if words match title directly, moderate if in description
            if title_match:
                score = min(score, 0.20)
            elif desc_match:
                score = min(score, 0.32)

            # Accept if cosine distance is under 0.45 or keyword matched
            if score < 0.45 or has_keyword_match:
                scored_complaints.append((score, complaint))

        scored_complaints.sort(key=lambda x: x[0])
        similar_complaints = [c for score, c in scored_complaints[:3]]

        serializer = PublicComplaintSerializer(similar_complaints, many=True, context={'request': request})
        return Response(serializer.data)


class UpvoteComplaintView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id, *args, **kwargs):
        try:
            complaint = Complaint.objects.get(complaint_id=complaint_id)
            user_profile = getattr(request.user, 'profile', None)
            if user_profile and user_profile not in complaint.supporters.all():
                complaint.supporters.add(user_profile)

                # Автоматична ескалація пріоритету:
                # 1+ голос (приєднання іншого студента) піднімає 'low' -> 'medium'
                # 3+ голоси піднімають 'low' / 'medium' -> 'high'
                # 5+ голосів піднімають до 'critical'
                supporters_count = complaint.supporters.count()
                changed_priority = False
                if supporters_count >= 5 and complaint.priority != 'critical':
                    complaint.priority = 'critical'
                    changed_priority = True
                elif supporters_count >= 3 and complaint.priority in ['low', 'medium']:
                    complaint.priority = 'high'
                    changed_priority = True
                elif supporters_count >= 1 and complaint.priority == 'low':
                    complaint.priority = 'medium'
                    changed_priority = True

                if changed_priority:
                    complaint.save(update_fields=['priority'])

            return Response({
                'status': 'success',
                'supporters_count': complaint.supporters.count(),
                'priority': complaint.priority
            })
        except Complaint.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

