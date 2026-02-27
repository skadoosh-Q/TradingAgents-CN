#!/usr/bin/env python3
"""
容器内初始化脚本
在 backend 容器启动后执行，进行数据库初始化和系统配置
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tradingagents.utils.logging_manager import get_logger

logger = get_logger('container_init')

# 从环境变量读取配置
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb")
MONGODB_PORT = int(os.getenv("MONGODB_PORT", "27017"))
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME", "admin")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD", "tradingagents123")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "tradingagents")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "tradingagents123")


async def wait_for_mongodb(max_retries=30, retry_interval=2):
    """等待 MongoDB 启动完成"""
    logger.info("⏳ 等待 MongoDB 启动...")
    
    from pymongo import MongoClient
    from pymongo.errors import ServerSelectionTimeoutError
    
    for i in range(max_retries):
        try:
            # 构建 MongoDB 连接字符串
            mongo_url = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}:{MONGODB_PORT}/{MONGODB_DATABASE}?authSource={MONGODB_AUTH_SOURCE}"
            
            client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
            client.server_info()
            logger.info("✅ MongoDB 连接成功")
            return client
            
        except (ServerSelectionTimeoutError, Exception) as e:
            if i < max_retries - 1:
                logger.warning(f"⏳ MongoDB 未就绪 ({i+1}/{max_retries})，{retry_interval}秒后重试...")
                await asyncio.sleep(retry_interval)
            else:
                logger.error(f"❌ MongoDB 启动失败: {e}")
                raise


async def wait_for_redis(max_retries=30, retry_interval=2):
    """等待 Redis 启动完成"""
    logger.info("⏳ 等待 Redis 启动...")
    
    import redis
    
    for i in range(max_retries):
        try:
            redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=0,
                socket_timeout=5
            )
            redis_client.ping()
            logger.info("✅ Redis 连接成功")
            return redis_client
            
        except Exception as e:
            if i < max_retries - 1:
                logger.warning(f"⏳ Redis 未就绪 ({i+1}/{max_retries})，{retry_interval}秒后重试...")
                await asyncio.sleep(retry_interval)
            else:
                logger.error(f"❌ Redis 启动失败: {e}")
                raise


async def create_database_indexes(db):
    """创建数据库索引"""
    logger.info("📊 创建数据库索引...")
    
    try:
        # 用户相关索引
        db.users.create_index([("username", 1)], unique=True)
        db.users.create_index([("email", 1)], unique=True)
        db.user_sessions.create_index([("user_id", 1)])
        db.user_activities.create_index([("user_id", 1), ("created_at", -1)])
        
        # 股票数据索引
        db.stock_basic_info.create_index([("code", 1), ("source", 1)], unique=True)
        db.stock_basic_info.create_index([("code", 1)])
        db.stock_basic_info.create_index([("source", 1)])
        db.stock_basic_info.create_index([("market", 1)])
        db.market_quotes.create_index([("code", 1)], unique=True)
        db.stock_news.create_index([("code", 1), ("published_at", -1)])
        
        # 分析相关索引
        db.analysis_tasks.create_index([("user_id", 1), ("created_at", -1)])
        db.analysis_reports.create_index([("task_id", 1)])
        
        # 系统配置索引
        db.system_config.create_index([("key", 1)], unique=True)
        db.operation_logs.create_index([("created_at", -1)])
        
        logger.info("✅ 数据库索引创建完成")
        
    except Exception as e:
        logger.error(f"❌ 创建数据库索引失败: {e}")


async def create_system_config(db):
    """创建系统配置"""
    logger.info("⚙️ 创建系统配置...")
    
    try:
        system_configs = [
            {
                "key": "system_version",
                "value": "v1.0.0-preview",
                "description": "系统版本号",
                "updated_at": datetime.utcnow()
            },
            {
                "key": "max_concurrent_tasks",
                "value": 3,
                "description": "最大并发分析任务数",
                "updated_at": datetime.utcnow()
            },
            {
                "key": "default_research_depth",
                "value": 2,
                "description": "默认分析深度",
                "updated_at": datetime.utcnow()
            },
            {
                "key": "enable_realtime_pe_pb",
                "value": True,
                "description": "启用实时PE/PB计算",
                "updated_at": datetime.utcnow()
            }
        ]
        
        for config in system_configs:
            db.system_config.replace_one(
                {"key": config["key"]},
                config,
                upsert=True
            )
        
        logger.info("✅ 系统配置创建完成")
        
    except Exception as e:
        logger.error(f"❌ 创建系统配置失败: {e}")


async def init_llm_providers(db):
    """初始化大模型厂家数据"""
    logger.info("🏢 初始化大模型厂家数据...")
    
    try:
        providers_collection = db["llm_providers"]
        
        # 预设厂家数据
        providers_data = [
            {
                "name": "openai",
                "display_name": "OpenAI",
                "description": "OpenAI是人工智能领域的领先公司，提供GPT系列模型",
                "website": "https://openai.com",
                "api_doc_url": "https://platform.openai.com/docs",
                "default_base_url": "https://api.openai.com/v1",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "image", "vision", "function_calling", "streaming"]
            },
            {
                "name": "anthropic",
                "display_name": "Anthropic",
                "description": "Anthropic专注于AI安全研究，提供Claude系列模型",
                "website": "https://anthropic.com",
                "api_doc_url": "https://docs.anthropic.com",
                "default_base_url": "https://api.anthropic.com",
                "is_active": True,
                "supported_features": ["chat", "completion", "function_calling", "streaming"]
            },
            {
                "name": "google",
                "display_name": "Google AI",
                "description": "Google的人工智能平台，提供Gemini系列模型",
                "website": "https://ai.google.dev",
                "api_doc_url": "https://ai.google.dev/docs",
                "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "vision", "function_calling", "streaming"]
            },
            {
                "name": "zhipu",
                "display_name": "智谱AI",
                "description": "智谱AI提供GLM系列中文大模型",
                "website": "https://zhipuai.cn",
                "api_doc_url": "https://open.bigmodel.cn/doc",
                "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "function_calling", "streaming"]
            },
            {
                "name": "deepseek",
                "display_name": "DeepSeek",
                "description": "DeepSeek提供高性能的AI推理服务",
                "website": "https://www.deepseek.com",
                "api_doc_url": "https://platform.deepseek.com/api-docs",
                "default_base_url": "https://api.deepseek.com",
                "is_active": True,
                "supported_features": ["chat", "completion", "function_calling", "streaming"]
            },
            {
                "name": "dashscope",
                "display_name": "阿里云百炼",
                "description": "阿里云百炼大模型服务平台，提供通义千问等模型",
                "website": "https://bailian.console.aliyun.com",
                "api_doc_url": "https://help.aliyun.com/zh/dashscope/",
                "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "function_calling", "streaming"]
            },
            {
                "name": "siliconflow",
                "display_name": "硅基流动",
                "description": "硅基流动提供高性价比的AI推理服务，支持多种开源模型",
                "website": "https://siliconflow.cn",
                "api_doc_url": "https://docs.siliconflow.cn",
                "default_base_url": "https://api.siliconflow.cn/v1",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "function_calling", "streaming"]
            },
            {
                "name": "302ai",
                "display_name": "302.AI",
                "description": "302.AI是企业级AI聚合平台，提供多种主流大模型的统一接口",
                "website": "https://302.ai",
                "api_doc_url": "https://doc.302.ai",
                "default_base_url": "https://api.302.ai/v1",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "image", "vision", "function_calling", "streaming"]
            },
            {
                "name": "qianfan",
                "display_name": "千帆AI",
                "description": "千帆AI提供多款文言大模型",
                "website": "https://qianfan.ai",
                "api_doc_url": "https://qianfan.ai/docs",
                "default_base_url": "https://api.qianfan.ai",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "streaming"]
            },
            {
                "name": "openrouter",
                "display_name": "OpenRouter",
                "description": "OpenRouter提供对多家模型的统一调用接口",
                "website": "https://openrouter.ai",
                "api_doc_url": "https://docs.openrouter.ai",
                "default_base_url": "https://openrouter.ai/v1",
                "is_active": True,
                "supported_features": ["chat", "completion", "embedding", "streaming"]
            },
            {
                "name": "test",
                "display_name": "测试厂商",
                "description": "用于本地测试的大模型提供商",
                "website": "",
                "api_doc_url": "",
                "default_base_url": "",
                "is_active": True,
                "supported_features": ["chat"]
            }
        ]
        
        # 检查是否已存在数据（使用同步方法）
        existing_count = providers_collection.count_documents({})
        if existing_count == 0:
            # 插入新数据
            for provider_data in providers_data:
                provider_data["created_at"] = datetime.utcnow()
                provider_data["updated_at"] = datetime.utcnow()
                
                try:
                    result = providers_collection.insert_one(provider_data)
                    logger.info(f"✅ 添加厂家: {provider_data['display_name']}")
                except Exception as e:
                    logger.warning(f"⚠️  添加厂家 {provider_data['display_name']} 失败: {e}")
            
            logger.info(f"✅ 共添加 {len(providers_data)} 个大模型厂家")
        else:
            logger.info(f"✓ 大模型厂家数据已存在 ({existing_count} 个)")
        
    except Exception as e:
        logger.error(f"❌ 初始化大模型厂家失败: {e}")
        import traceback
        traceback.print_exc()


async def init_model_catalog(db):
    """初始化模型目录"""
    logger.info("📦 初始化模型目录...")
    
    try:
        catalog_collection = db["model_catalog"]
        
        # 检查是否已有数据
        existing_count = catalog_collection.count_documents({})
        if existing_count > 0:
            logger.info(f"✓ 模型目录数据已存在 ({existing_count} 条)")
            return
        
        # 初始化通义千问模型目录
        dashscope_catalog = {
            "provider": "dashscope",
            "provider_name": "通义千问",
            "models": [
                {
                    "name": "qwen-turbo",
                    "display_name": "Qwen Turbo - 快速经济 (1M上下文)",
                    "input_price_per_1k": 0.0003,
                    "output_price_per_1k": 0.0003,
                    "context_length": 1000000,
                    "currency": "CNY",
                    "description": "Qwen2.5-Turbo，支持100万tokens超长上下文"
                },
                {
                    "name": "qwen-plus",
                    "display_name": "Qwen Plus - 平衡推荐",
                    "input_price_per_1k": 0.0008,
                    "output_price_per_1k": 0.002,
                    "context_length": 32768,
                    "currency": "CNY"
                },
                {
                    "name": "qwen-plus-latest",
                    "display_name": "Qwen Plus Latest - 最新平衡",
                    "input_price_per_1k": 0.0008,
                    "output_price_per_1k": 0.002,
                    "context_length": 32768,
                    "currency": "CNY"
                },
                {
                    "name": "qwen-max",
                    "display_name": "Qwen Max - 最强性能",
                    "input_price_per_1k": 0.02,
                    "output_price_per_1k": 0.06,
                    "context_length": 8192,
                    "currency": "CNY"
                }
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # 初始化 OpenAI 模型目录
        openai_catalog = {
            "provider": "openai",
            "provider_name": "OpenAI",
            "models": [
                {
                    "name": "gpt-4o",
                    "display_name": "GPT-4o",
                    "input_price_per_1k": 0.005,
                    "output_price_per_1k": 0.015,
                    "context_length": 128000,
                    "currency": "USD"
                },
                {
                    "name": "gpt-4-turbo",
                    "display_name": "GPT-4 Turbo",
                    "input_price_per_1k": 0.01,
                    "output_price_per_1k": 0.03,
                    "context_length": 128000,
                    "currency": "USD"
                },
                {
                    "name": "gpt-3.5-turbo",
                    "display_name": "GPT-3.5 Turbo",
                    "input_price_per_1k": 0.0005,
                    "output_price_per_1k": 0.0015,
                    "context_length": 16385,
                    "currency": "USD"
                }
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # 初始化 DeepSeek 模型目录
        deepseek_catalog = {
            "provider": "deepseek",
            "provider_name": "DeepSeek",
            "models": [
                {
                    "name": "deepseek-chat",
                    "display_name": "DeepSeek Chat",
                    "input_price_per_1k": 0.0014,
                    "output_price_per_1k": 0.0028,
                    "context_length": 64000,
                    "currency": "CNY"
                }
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # 初始化 Google 模型目录
        google_catalog = {
            "provider": "google",
            "provider_name": "Google AI",
            "models": [
                {
                    "name": "gemini-2.0-flash",
                    "display_name": "Gemini 2.0 Flash",
                    "input_price_per_1k": 0.075,
                    "output_price_per_1k": 0.3,
                    "context_length": 1000000,
                    "currency": "USD"
                },
                {
                    "name": "gemini-1.5-pro",
                    "display_name": "Gemini 1.5 Pro",
                    "input_price_per_1k": 1.25,
                    "output_price_per_1k": 5.0,
                    "context_length": 2000000,
                    "currency": "USD"
                }
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # 插入模型目录
        catalogs_to_insert = [dashscope_catalog, openai_catalog, deepseek_catalog, google_catalog]
        
        # 添加千帆与硅基流动目录
        qianfan_catalog = {
            "provider": "qianfan",
            "provider_name": "千帆AI",
            "models": [
                {"name": "ernie-3.5-8k", "display_name": "Ernie 3.5 8K", "input_price_per_1k": None, "output_price_per_1k": None, "context_length": 8000, "currency": "CNY"},
                {"name": "ernie-4.0-turbo-8k", "display_name": "Ernie 4.0 Turbo 8K", "input_price_per_1k": None, "output_price_per_1k": None, "context_length": 8000, "currency": "CNY"}
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        siliconflow_catalog_more = {
            "provider": "siliconflow",
            "provider_name": "硅基流动",
            "models": [
                {"name": "Pro/deepseek-ai/DeepSeek-V3.2-Exp", "display_name": "DeepSeek V3.2 Exp", "input_price_per_1k": 2, "output_price_per_1k": 3, "context_length": 8000, "currency": "CNY"},
                {"name": "Pro/deepseek-ai/DeepSeek-V3.2", "display_name": "DeepSeek V3.2", "input_price_per_1k": 0.002, "output_price_per_1k": 0.003, "context_length": 8000, "currency": "CNY"}
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        catalogs_to_insert.extend([qianfan_catalog, siliconflow_catalog_more])
        # 包含 openrouter 和测试型号的简单目录
        openrouter_catalog = {
            "provider": "openrouter",
            "provider_name": "OpenRouter",
            "models": [
                {"name": "openai/gpt-5", "display_name": "OpenAI GPT-5", "input_price_per_1k": 0.00125, "output_price_per_1k": 0.01, "context_length": 4000, "currency": "USD"}
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        test_catalog = {
            "provider": "test",
            "provider_name": "测试厂商",
            "models": [
                {"name": "test1", "display_name": "test1", "input_price_per_1k": 0.002, "output_price_per_1k": 0.001, "context_length": 4000, "currency": "CNY"}
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        catalogs_to_insert.extend([openrouter_catalog, test_catalog])
        
        for catalog in catalogs_to_insert:
            try:
                catalog_collection.insert_one(catalog)
                logger.info(f"✅ 初始化模型目录: {catalog['provider_name']} ({len(catalog['models'])} 个模型)")
            except Exception as e:
                logger.warning(f"⚠️  初始化 {catalog['provider_name']} 失败: {e}")
        
        logger.info(f"✅ 总共初始化 {len(catalogs_to_insert)} 个厂家的模型目录")
        
    except Exception as e:
        logger.error(f"❌ 初始化模型目录失败: {e}")
        import traceback
        traceback.print_exc()


async def create_default_admin_user(db):
    """创建默认管理员用户"""
    logger.info("👤 创建默认管理员用户...")

    try:
        # 使用用户服务创建管理员
        from app.services.user_service import user_service

        # 从环境变量或配置文件读取管理员密码
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        admin_email = os.getenv("ADMIN_EMAIL", "admin@tradingagents.cn")

        # 检查管理员用户是否已存在
        existing_admin = db.users.find_one({"username": "admin"})
        if existing_admin:
            logger.info("✓ 管理员用户已存在")
            return

        # 创建管理员用户
        admin_user = await user_service.create_admin_user(
            username="admin",
            password=admin_password,
            email=admin_email
        )

        if admin_user:
            logger.info("✅ 创建管理员用户成功")
            logger.info(f"   用户名: admin")
            logger.info(f"   邮箱: {admin_email}")
            logger.info("   ⚠️  请在首次登录后立即修改密码！")
        else:
            logger.info("✓ 管理员用户已存在")

    except Exception as e:
        logger.error(f"❌ 创建管理员用户失败: {e}")
        import traceback
        traceback.print_exc()


async def init_mongodb():
    """初始化 MongoDB 数据库"""
    logger.info("🗄️ 初始化 MongoDB 数据库...")
    
    try:
        from pymongo import MongoClient
        
        # 等待 MongoDB 启动
        mongo_url = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}:{MONGODB_PORT}/{MONGODB_DATABASE}?authSource={MONGODB_AUTH_SOURCE}"
        client = MongoClient(mongo_url)
        db = client[MONGODB_DATABASE]
        
        # 创建集合
        collections_to_create = [
            "users", "user_sessions", "user_activities",
            "stock_basic_info", "stock_financial_data", "market_quotes", "stock_news",
            "analysis_tasks", "analysis_reports", "analysis_progress",
            "screening_results", "favorites", "tags",
            "system_config", "model_config", "sync_status", "operation_logs",
            "llm_providers", "model_catalog"  # 添加大模型相关集合
        ]
        
        for collection_name in collections_to_create:
            if collection_name not in db.list_collection_names():
                db.create_collection(collection_name)
                logger.info(f"✅ 创建集合: {collection_name}")
        
        # 创建索引
        await create_database_indexes(db)
        
        # 创建系统配置
        await create_system_config(db)
        
        # 初始化大模型厂家数据
        await init_llm_providers(db)
        
        # 初始化模型目录
        await init_model_catalog(db)
        
        # 创建管理员用户
        await create_default_admin_user(db)
        
        logger.info("✅ MongoDB 初始化完成")
        return True
        
    except Exception as e:
        logger.error(f"❌ MongoDB 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    logger.info("\n" + "=" * 60)
    logger.info("🚀 开始容器内初始化...")
    logger.info("=" * 60)
    logger.info(f"MongoDB: {MONGODB_HOST}:{MONGODB_PORT}/{MONGODB_DATABASE}")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    
    try:
        # 1. 等待 MongoDB 启动
        await wait_for_mongodb()
        
        # 2. 等待 Redis 启动
        await wait_for_redis()
        
        # 3. 初始化 MongoDB 数据库
        if not await init_mongodb():
            logger.error("❌ 数据库初始化失败")
            return False
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ 容器内初始化完成！")
        logger.info("=" * 60)
        logger.info("\n📋 系统信息:")
        logger.info("- 后端 API: http://localhost:8000")
        logger.info("- API 文档: http://localhost:8000/docs")
        logger.info("\n🔐 登录信息:")
        logger.info("- 用户名: admin")
        logger.info("- 密码: 见 ADMIN_PASSWORD 环境变量 (默认: admin123)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
