# TradingAgents 中文增强版 (个人维护版)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-cn--0.1.15-green.svg)](./VERSION)
[![Documentation](https://img.shields.io/badge/docs-中文文档-green.svg)](./docs/)
[![Original](https://img.shields.io/badge/基于-TauricResearch/TradingAgents-orange.svg)](https://github.com/TauricResearch/TradingAgents)

>
> 个人维护版本  
>
> 基于[hsliuping/TradingAgents-CN](https://github.com/TauricResearch) v1.0.0-preview 

原版`TradingAgents-CN v1.0.0-preview`发布后，很久没更新了，使用过程中发现新闻获取不到，遂进行了代码修复。

## 使用
见[原项目使用文档](https://github.com/hsliuping/TradingAgents-CN?tab=readme-ov-file#-%E4%BD%BF%E7%94%A8%E6%8C%87%E5%8D%97).

本项目推荐使用docker.

## 特别注意
本仓库基于`hsliuping/TradingAgents-CN` **v1.0.0-preview**版本修改。

docker安装时，拉取的仍然是官方镜像，本仓库是通过挂载的方式将本地代码挂载进docker容器中覆盖原项目代码。

例如在`docker-compose.hub.nginx.arm.yml`中
```yml
...
  backend:
    image: hsliup/tradingagents-backend-arm64:latest
    # image: hsliup/tradingagents-backend-arm64:v1.0.0-preview
    ...
    volumes:
      ...
      # 挂载本地代码覆盖原代码，以修复或新增功能
      - ./app:/app/app
      - ./tradingagents:/app/tradingagents
      - ./scripts:/app/scripts
      ...
    ...
  ...
...
```

> ⚠️ 如果官方`latest`版本不是`v1.0.0-preview`了，可能会与修改的代码冲突造成程序异常，可固定拉取的版本
`image: hsliup/tradingagents-backend-arm64:v1.0.0-preview`
> 
> 也可以选择使用本地构建
```yml
...
  backend:
    # image: hsliup/tradingagents-backend-arm64:latest
    # image: hsliup/tradingagents-backend-arm64:v1.0.0-preview
    build:
      context: .
      dockerfile: Dockerfile.backend
    ...
    volumes:
      ...
      # 挂载本地代码覆盖原代码，以修复或新增功能
      - ./app:/app/app
      - ./tradingagents:/app/tradingagents
      - ./scripts:/app/scripts
      ...
    ...
  ...
...
```
