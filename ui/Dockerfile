FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html styles.css app.js config.compose.js /usr/share/nginx/html/
RUN mv /usr/share/nginx/html/config.compose.js /usr/share/nginx/html/config.js

EXPOSE 80
