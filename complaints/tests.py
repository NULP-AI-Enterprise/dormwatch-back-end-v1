from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .admin import CommentAdmin
from .models import Comment, Complaint, Role, UserProfile


class CommentOwnershipTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for name, role, staff, superuser in [
            ("student", "student", False, False),
            ("worker", "worker", False, False),
            ("admin", "admin", False, False),
            ("staff", "admin", True, False),
            ("superuser", "admin", True, True),
        ]:
            user = User.objects.create_user(
                username=name, email=f"{name}@lpnu.ua", password=None,
                is_staff=staff, is_superuser=superuser,
            )
            UserProfile.objects.create(
                user=user, email=user.email, first_name=name,
                role=Role.objects.get_or_create(role_name=role)[0],
            )
            cls.users[name] = user
        cls.complaint = Complaint.objects.create(
            user=cls.users["student"].profile,
            title="Перевірка прав на коментарі", description="Тест",
        )

    def authenticate(self, user):
        token = RefreshToken.for_user(user)
        token["email"] = user.email
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def comment(self, user):
        return Comment.objects.create(
            user=user.profile, complaint=self.complaint, description="Тестовий коментар",
        )

    def test_every_role_can_delete_its_own_comment(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                comment = self.comment(user)
                self.authenticate(user)
                response = self.client.delete(f"/api/comments/{comment.pk}/")
                self.assertEqual(response.status_code, 204)
                self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_no_role_can_delete_another_authors_comment(self):
        for author_name, author in self.users.items():
            comment = self.comment(author)
            for actor_name, actor in self.users.items():
                if actor.pk == author.pk:
                    continue
                with self.subTest(author=author_name, actor=actor_name):
                    self.authenticate(actor)
                    response = self.client.delete(f"/api/comments/{comment.pk}/")
                    self.assertEqual(response.status_code, 403)
                    self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_anonymous_cannot_delete(self):
        comment = self.comment(self.users["student"])
        response = self.client.delete(f"/api/comments/{comment.pk}/")
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_missing_comment_returns_not_found(self):
        self.authenticate(self.users["admin"])
        response = self.client.delete("/api/comments/999999/")
        self.assertEqual(response.status_code, 404)

    def test_django_admin_has_no_superuser_or_bulk_delete_bypass(self):
        request = RequestFactory().get("/admin/complaints/comment/")
        request.user = self.users["superuser"]
        model_admin = CommentAdmin(Comment, admin.site)
        own = self.comment(request.user)
        foreign = self.comment(self.users["student"])
        self.assertTrue(model_admin.has_delete_permission(request, own))
        self.assertFalse(model_admin.has_delete_permission(request, foreign))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertNotIn("delete_selected", model_admin.get_actions(request))
        self.assertIn("user", model_admin.get_readonly_fields(request, foreign))

class ResourceDecimalValidationTests(SimpleTestCase):
    def fields(self):
        from .serializers import ComplaintResourceCreateSerializer, ResourceSerializer
        return [
            ("quantity", ComplaintResourceCreateSerializer().fields["quantity"]),
            ("usage_price", ComplaintResourceCreateSerializer().fields["unit_cost"]),
            ("catalog_price", ResourceSerializer().fields["unit_cost"]),
        ]

    def test_maximum_supported_amount_is_accepted(self):
        from decimal import Decimal
        for name, field in self.fields():
            with self.subTest(field=name):
                self.assertEqual(field.run_validation("99999999.99"), Decimal("99999999.99"))

    def test_oversized_amount_explains_the_limit_in_ukrainian(self):
        from rest_framework.exceptions import ValidationError
        for name, field in self.fields():
            for value in ["100000000", "100000000.00", "999999999999999999999999"]:
                with self.subTest(field=name, value=value):
                    with self.assertRaises(ValidationError) as error:
                        field.run_validation(value)
                    message = str(error.exception.detail[0])
                    self.assertIn("99 999 999,99", message)
                    self.assertTrue(message.startswith("Кількість" if name == "quantity" else "Ціна"))

    def test_excess_precision_explains_decimal_places(self):
        from rest_framework.exceptions import ValidationError
        for name, field in self.fields():
            with self.subTest(field=name):
                with self.assertRaises(ValidationError) as error:
                    field.run_validation("1.234")
                self.assertIn("не більше 2 знаків після коми", str(error.exception.detail[0]))

    def test_invalid_numbers_and_minimum_remain_rejected(self):
        from rest_framework.exceptions import ValidationError
        for name, field in self.fields():
            for value in ["NaN", "Infinity", "-1", "abc"] + (["0"] if name == "quantity" else []):
                with self.subTest(field=name, value=value):
                    with self.assertRaises(ValidationError):
                        field.run_validation(value)
