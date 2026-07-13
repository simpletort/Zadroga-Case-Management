FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ENV FUNCTION_TARGET=calculate_filing_deadline
EXPOSE 8080
CMD ["functions-framework", "--target=calculate_filing_deadline", "--signature-type=cloudevent"]
