# Notification Service — Services README Index

This folder contains documentation for each file in `services/notification/services/`.

| File | README | Purpose |
|---|---|---|
| `firestore_client.py` | [firestore_client.md](./firestore_client.md) | Shared Firestore database connection |
| `opt_out_service.py` | [opt_out_service.md](./opt_out_service.md) | SMS opt-out / suppression list (STOP/START) |
| `sms_service.py` | [sms_service.md](./sms_service.md) | Main SMS dispatch orchestrator |
| `tasks_service.py` | [tasks_service.md](./tasks_service.md) | Async SMS queuing via Cloud Tasks |
| `template_service.py` | [template_service.md](./template_service.md) | Firestore template fetch and rendering |
| `twilio_client.py` | [twilio_client.md](./twilio_client.md) | Twilio API wrapper and SMS length rules |
