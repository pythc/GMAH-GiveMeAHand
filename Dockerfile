FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system agent && adduser --system --ingroup agent agent

COPY pyproject.toml README.md ./
COPY configs ./configs
COPY skills ./skills
COPY memory ./memory
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER agent

EXPOSE 8080

CMD ["uvicorn", "agent_workflow.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
