FROM node:20-slim

WORKDIR /app

COPY package.json .
RUN npm install --production

COPY index.js .

# Create auth state directory
RUN mkdir -p /app/auth_state

EXPOSE 3001

CMD ["node", "index.js"]
