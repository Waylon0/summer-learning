FROM node:22-alpine

WORKDIR /app

# 复制依赖文件（利用 Docker 缓存层）
COPY package.json package-lock.json* ./

# 安装依赖
RUN npm ci 2>/dev/null || npm install

# 复制应用代码
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
