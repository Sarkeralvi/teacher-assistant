# TECH STACK DECISION

## Status
Locked by Human. This decision is authoritative for Week 1 scaffold and architecture alignment.

## Frontend
- Next.js App Router
- TypeScript
- Tailwind CSS

## Backend
- FastAPI
- Python
- Pydantic
- SQLAlchemy 2.x
- Alembic

## Database
- PostgreSQL

## Worker / Queue
- Redis
- RQ

## Storage
- Local filesystem for v0
- Must be wrapped behind a storage adapter
- Future storage targets: S3 and/or MinIO

## AI
- Custom Brain Adapter
- custom Brain Adapter is the only AI boundary
- No direct LLM calls from routes, UI, services, workers, grading modules, or domain modules
- All LLM calls must go through Brain Adapter

## Document / PDF / Image Processing
- PyMuPDF for PDF page extraction
- Pillow for image processing
- OpenCV for image preprocessing

## Export
- openpyxl for Excel export

## Development
- Docker Compose
- Makefile

## Testing
- pytest for backend
- frontend tests minimal in Week 1

## Rejected Alternatives
No alternatives are active. Do not introduce another framework, queue, ORM, migration tool, or frontend stack without Human approval.

## Architectural Consequences
1. Backend domain logic must be Python-first and testable with pytest.
2. Database models use SQLAlchemy 2.x style and migrations use Alembic.
3. Background jobs use RQ workers connected to Redis.
4. Uploaded files and generated artifacts go through a storage adapter even while stored locally.
5. Excel export uses openpyxl and reads approved final-grade records only.
6. PDF/image preprocessing belongs in worker-side document modules, not frontend code.
7. LLM provider SDKs are forbidden outside Brain Adapter provider implementations.
