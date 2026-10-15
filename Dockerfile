FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 racing
COPY --chown=racing:racing app ./app
COPY --chown=racing:racing run.py gunicorn.conf.py LICENSE ./
RUN mkdir -p /app/instance && chown racing:racing /app/instance
USER racing
EXPOSE 8080
CMD ["gunicorn", "--preload", "--bind", "0.0.0.0:8080", "--workers", "2", "--access-logfile", "-", "run:app"]
