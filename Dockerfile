# Use an official Python runtime as a parent image
FROM python

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY server.py          /app/server.py
COPY requirements.txt   /app/requirements.txt
COPY www                /app/www

RUN echo "nameserver 1.1.1.1" > /etc/resolv.conf && \
    pip install --no-cache-dir -r requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN rm -f /app/requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Run app.py when the container launches
CMD ["python", "server.py", "-p", "8080"]