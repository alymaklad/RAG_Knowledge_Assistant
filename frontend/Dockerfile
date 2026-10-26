# Development: Vite dev server with /api proxied to the api container.
FROM node:22-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# Build the static bundle.
FROM dev AS build
RUN npm run build

# Production: Nginx serves the SPA and proxies /api to FastAPI on the same origin.
FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_UPSTREAM=http://api:8000
EXPOSE 80
