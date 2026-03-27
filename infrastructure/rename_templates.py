from google.cloud import firestore

db = firestore.Client(project='simpletort-zadroga-dev', database='simpletort-dev')
col = db.collection('notificationTemplates')

renames = [
    ('welcome-email',    'welcome_email'),
    ('welcome-sms',      'welcome_sms'),
    ('reminder-48hr-sms',   'reminder_48hr_sms'),
    ('reminder-48hr-email', 'reminder_48hr_email'),
    ('reminder-7day-sms',   'reminder_7day_sms'),
    ('reminder-7day-email', 'reminder_7day_email'),
]

for old_id, new_id in renames:
    old_doc = col.document(old_id).get()
    if old_doc.exists:
        col.document(new_id).set(old_doc.to_dict())
        col.document(old_id).delete()
        print(f'Renamed: {old_id} -> {new_id}')
    else:
        print(f'Skipped: {old_id} (not found or already renamed)')

print('Done.')
