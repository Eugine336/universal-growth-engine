FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV UGIE_DB_URL=sqlite:///data/ugie.db
ENV UGIE_CONFIG_DIR=domain/examples

EXPOSE 8000

CMD ["uvicorn", "api.rest.app:app", "--host", "0.0.0.0", "--port", "8000"]
