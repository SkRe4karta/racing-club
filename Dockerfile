FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 racing
COPY --chown=racing:racing app ./app
COPY --chown=racing:racing migrations ./migrations
COPY --chown=racing:racing run.py gunicorn.conf.py LICENSE ./
RUN mkdir -p /app/instance && chown racing:racing /app/instance
FROM base AS checks
COPY --chown=racing:racing tests ./tests
COPY --chown=racing:racing scripts ./scripts
COPY --chown=racing:racing seed.py verify_acceptance.py verify_modernization.py ./
USER racing
CMD ["python", "-m", "unittest", "tests.beta1_corrections_suite", "-v"]

FROM base AS runtime
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Racing Club" \
      org.opencontainers.image.version="2.0.0-beta.1" \
      org.opencontainers.image.revision=$VCS_REF
USER racing
EXPOSE 8080
CMD ["gunicorn", "--preload", "--bind", "0.0.0.0:8080", "--workers", "2", "--access-logfile", "-", "run:app"]
