FROM python:3.13-alpine

WORKDIR /app
COPY app.py /app/app.py

USER 10001:10001

EXPOSE 8080
CMD ["python", "/app/app.py"]