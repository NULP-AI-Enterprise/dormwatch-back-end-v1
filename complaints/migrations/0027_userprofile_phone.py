from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('complaints', '0026_alter_userprofile_is_email_verified'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='phone',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
