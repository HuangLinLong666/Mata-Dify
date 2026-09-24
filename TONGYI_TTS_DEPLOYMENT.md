# Tongyi TTS 自定义镜像部署

本仓库在 Dify API 层兼容 Tongyi `qwen3-tts-flash`：插件虽然声明 MP3，
实际可能返回一个或多个完整 WAV 容器。

## 使用 GitHub Actions 发布镜像

1. 将本仓库推送到 GitHub。
2. 打开 **Actions**，手动运行 **Build Tongyi-compatible Dify API**。
3. 将生成的 GHCR Package 设为公开；如果保持私有，则每台部署机器都需要先登录 GHCR。
4. 在部署机器上将 `docker/.env.example` 复制为 `docker/.env`，然后增加：

   ```dotenv
   DIFY_API_IMAGE=ghcr.io/OWNER/REPOSITORY/dify-api:tongyi-tts-latest
   GUNICORN_TIMEOUT=900
   ```

5. 启动或更新 Dify：

   ```bash
   cd docker
   docker compose pull api api_websocket worker worker_beat
   docker compose up -d
   ```

生产环境建议使用工作流生成的固定 SHA 标签，不要使用会变化的 `tongyi-tts-latest`。

## 改为本地构建

在仓库根目录运行：

```bash
docker build --pull=false -f api/Dockerfile.tongyi-tts -t dify-api:tongyi-tts .
```

然后在 `docker/.env` 中增加：

```dotenv
DIFY_API_IMAGE=dify-api:tongyi-tts
GUNICORN_TIMEOUT=900
```

Tongyi `qwen3-tts-flash` 会在 API 层按每段最多 80 个字符进行串行合成。长课时开始播放前
可能需要等待数分钟；较长的 Gunicorn 超时用于避免合成完成前连接被中断。

`plugin_daemon` 仍然使用官方镜像。不要修改 `docker/volumes/plugin_daemon/cwd`
下面的文件；它们属于运行时文件，插件重新安装或升级时可能被覆盖。
