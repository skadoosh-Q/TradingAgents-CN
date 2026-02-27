#!/usr/bin/env python3
"""
数据库诊断脚本 - 检查初始化是否成功
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tradingagents.utils.logging_manager import get_logger

logger = get_logger('db_check')

# 从环境变量读取配置
MONGODB_HOST = os.getenv("MONGODB_HOST", "localhost")
MONGODB_PORT = int(os.getenv("MONGODB_PORT", "27017"))
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME", "admin")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD", "tradingagents123")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "tradingagents")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")


def check_database():
    """检查数据库数据"""
    logger.info("=" * 60)
    logger.info("🔍 开始数据库检查...")
    logger.info("=" * 60)
    
    try:
        from pymongo import MongoClient
        
        # 连接数据库
        mongo_url = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}:{MONGODB_PORT}/{MONGODB_DATABASE}?authSource={MONGODB_AUTH_SOURCE}"
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        client.server_info()
        db = client[MONGODB_DATABASE]
        
        logger.info("✅ MongoDB 连接成功\n")
        
        # 检查大模型厂家数据
        logger.info("📊 检查大模型厂家数据 (llm_providers):")
        providers_count = db.llm_providers.count_documents({})
        logger.info(f"   总数: {providers_count} 条")
        
        if providers_count > 0:
            providers = db.llm_providers.find().limit(3)
            for i, provider in enumerate(providers, 1):
                logger.info(f"   {i}. {provider.get('display_name', 'Unknown')}")
                logger.info(f"      - Provider: {provider.get('name', 'N/A')}")
                logger.info(f"      - Active: {provider.get('is_active', False)}")
        logger.info()
        
        # 检查模型目录数据
        logger.info("📦 检查模型目录数据 (model_catalog):")
        catalog_count = db.model_catalog.count_documents({})
        logger.info(f"   总数: {catalog_count} 条")
        
        if catalog_count > 0:
            catalogs = db.model_catalog.find().limit(3)
            for i, catalog in enumerate(catalogs, 1):
                models_count = len(catalog.get('models', []))
                logger.info(f"   {i}. {catalog.get('provider_name', 'Unknown')}")
                logger.info(f"      - Provider: {catalog.get('provider', 'N/A')}")
                logger.info(f"      - 模型数: {models_count}")
                if models_count > 0:
                    logger.info(f"        模型示例: {catalog['models'][0].get('display_name', 'N/A')}")
        logger.info()
        
        # 检查系统配置
        logger.info("⚙️ 检查系统配置数据 (system_config):")
        config_count = db.system_config.count_documents({})
        logger.info(f"   总数: {config_count} 条")
        
        if config_count > 0:
            configs = db.system_config.find().limit(3)
            for i, config in enumerate(configs, 1):
                logger.info(f"   {i}. {config.get('key', 'Unknown')}: {config.get('value', 'N/A')}")
        logger.info()
        
        # 检查用户数据
        logger.info("👤 检查用户数据 (users):")
        users_count = db.users.count_documents({})
        logger.info(f"   总数: {users_count} 条")
        
        if users_count > 0:
            users = db.users.find().limit(3)
            for i, user in enumerate(users, 1):
                logger.info(f"   {i}. {user.get('username', 'Unknown')} ({user.get('role', 'user')})")
        logger.info()
        
        # 汇总
        logger.info("=" * 60)
        logger.info("📋 数据初始化状态汇总:")
        logger.info(f"   ✅ 大模型厂家: {providers_count} 条" if providers_count > 0 else "   ❌ 大模型厂家: 未初始化")
        logger.info(f"   ✅ 模型目录: {catalog_count} 条" if catalog_count > 0 else "   ❌ 模型目录: 未初始化")
        logger.info(f"   ✅ 系统配置: {config_count} 条" if config_count > 0 else "   ❌ 系统配置: 未初始化")
        logger.info(f"   ✅ 用户数据: {users_count} 条" if users_count > 0 else "   ❌ 用户数据: 未初始化")
        logger.info("=" * 60)
        
        # 建议
        if providers_count == 0:
            logger.warning("\n⚠️  大模型厂家数据未初始化！")
            logger.warning("   请运行: python scripts/container_init.py")
        
        if catalog_count == 0:
            logger.warning("\n⚠️  模型目录数据未初始化！")
            logger.warning("   请运行: python scripts/container_init.py")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = check_database()
    sys.exit(0 if success else 1)
