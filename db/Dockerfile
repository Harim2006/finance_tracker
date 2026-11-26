FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache ca-certificates libstdc++

COPY db/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --only-binary=pymssql -r requirements.txt

COPY db/init.py db/migrate.py db/init.sql db/sql_connection.py db/azure_init.py /app/db/

COPY services/budget/migrations/ /app/services/budget/migrations/

COPY services/bills/migrations/ /app/services/bills/migrations/

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

USER appuser

CMD ["sh", "-c", "python db/init.py && python db/migrate.py"]
