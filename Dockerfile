# Use an official Python runtime as a parent image
FROM python:3.11-slim-bullseye

# Set the working directory in the container
WORKDIR /MoneyPrinterTurbo

ENV PYTHONPATH="/MoneyPrinterTurbo"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        imagemagick \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fix security policy for ImageMagick (allow @filename reads for subtitle rendering)
RUN sed -i '/<policy domain="path" rights="none" pattern="@\*"/d' /etc/ImageMagick-6/policy.xml

# Copy only the requirements.txt first to leverage Docker cache
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir --retries 3 --timeout 60 -r requirements.txt

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /MoneyPrinterTurbo appuser

# Now copy the rest of the codebase into the image
COPY . .

# Create storage directory and set ownership
RUN mkdir -p /MoneyPrinterTurbo/storage && chown -R appuser:appuser /MoneyPrinterTurbo

# Run as non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 8501

# Command to run the application
CMD ["streamlit", "run", "./webui/Main.py","--browser.serverAddress=127.0.0.1","--server.enableCORS=True","--browser.gatherUsageStats=False"]
