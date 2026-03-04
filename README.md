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

如果想自己做80端口反代，则启动:
```shell
docker compose up -d
```
默认compose配置文件中不包含nginx服务，需要自己配置访问服务

正常启动
```shell
docker-compose -f docker-compose.hub.nginx.yml up -d
```
包含Nginx服务，启动后访问`localhost`即可打开

arm系统启动
```
docker-compose -f docker-compose.hub.nginx.arm.yml up -d
```

本项目推荐使用docker.

## 项目文档

- [WORKFLOW_ANALYSIS.md](./WORKFLOW_ANALYSIS.md) — 项目工作流程图与角色分析文档，包含Agent角色的提示词详解以及数据流向图和辩论机制说明。

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

## UPDATE
- 26-03-04
  - 修复`risk_manager.py`中`fundamentals_report`被错误赋值为`news_report`的BUG
  - 新增[WORKFLOW_ANALYSIS.md](./WORKFLOW_ANALYSIS.md)工作流程分析文档
- 26-02-12
  - 单股分析时, 增加"是否持仓"选项
- 26-02-11
  - 修复新闻获取不到的问题
