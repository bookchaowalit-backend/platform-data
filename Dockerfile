# Build from an explicit offline wheel bundle containing core 0.1.0 and all
# transitive dependencies. The bundle is a release input, never vendored state.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY wheels/ /wheels/
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-index --find-links=/wheels "setuptools>=75" \
    && python -m pip install --no-index --find-links=/wheels --no-build-isolation .
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "platform_data", "serve"]
