FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FUNCTION_TARGET=on_case_updated
ENV FUNCTION_SIGNATURE_TYPE=cloudevent

CMD ["functions-framework", "--target=on_case_updated", "--signature-type=cloudevent"]
