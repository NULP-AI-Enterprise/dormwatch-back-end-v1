from django.db import migrations

CATEGORY_RENAMES = {
    "plumbing": "Сантехніка",
    "electricity": "Електрика",
    "furniture": "Меблі",
    "internet": "Інтернет",
}

def rename_categories(apps, schema_editor):
    ComplaintCategory = apps.get_model('complaints', 'ComplaintCategory')
    Complaint = apps.get_model('complaints', 'Complaint')
    for old_name, new_name in CATEGORY_RENAMES.items():
        existing = ComplaintCategory.objects.filter(name=new_name).first()
        old = ComplaintCategory.objects.filter(name=old_name).first()
        if existing and old:
            Complaint.objects.filter(category=old).update(category=existing)
            old.delete()
        elif old:
            old.name = new_name
            old.save()

class Migration(migrations.Migration):
    dependencies = [('complaints', '0007_place_unique_building_place_name')]
    operations = [migrations.RunPython(rename_categories, reverse_code=migrations.RunPython.noop)]
