# Backend image for a Hugging Face Docker Space (free CPU tier).
# Built from the contents of backend/ (see deploy/huggingface/prepare_space.py).
FROM python:3.11-slim

# Spaces run containers as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
RUN mkdir -p storage/hr-policies storage/profile-photos storage/employee-documents storage/ai \
    && chown -R user:user storage

USER user
ENV PYTHONPATH=/app \
    PORT=7860 \
    DATABASE_URL=sqlite+aiosqlite:///./storage/hrms.db \
    POLICY_UPLOAD_DIR=/app/storage/hr-policies \
    PROFILE_PHOTO_UPLOAD_DIR=/app/storage/profile-photos \
    EMPLOYEE_DOCUMENT_UPLOAD_DIR=/app/storage/employee-documents \
    EMBEDDING_CACHE_DIR=/app/storage/ai/models \
    AI_INDEX_PATH=/app/storage/ai/policy_index.db \
    ACCESS_TOKEN_EXPIRE_MINUTES=60

EXPOSE 7860
CMD ["sh", "scripts/start.sh"]
