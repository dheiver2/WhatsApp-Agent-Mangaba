FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json .
RUN npm install --production

COPY index.js .

# Create auth state directory
RUN mkdir -p /app/auth_state

EXPOSE 3001

CMD ["node", "index.js"]
