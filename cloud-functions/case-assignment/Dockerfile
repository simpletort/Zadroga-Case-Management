FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# functions-framework serves the function on port 8080
ENV PORT=8080
EXPOSE 8080

CMD ["functions-framework", "--target=case_assignment", "--port=8080", "--signature-type=cloudevent"]
