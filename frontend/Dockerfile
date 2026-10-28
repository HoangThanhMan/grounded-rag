FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# outside compose too: trust no proxy unless told which one
ENV REAL_IP_FROM=127.0.0.1
# rendered to /etc/nginx/conf.d/default.conf by the image entrypoint (envsubst)
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
