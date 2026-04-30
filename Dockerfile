FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e .

RUN mkdir -p outputs/audit outputs/backup

EXPOSE 8000

CMD ["uvicorn", "atividade_2.web:app", "--host", "0.0.0.0", "--port", "8000"]
