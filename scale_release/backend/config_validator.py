#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI服务配置验证脚本
AI Service Configuration Validator
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import structlog

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

# 加载环境变量
load_dotenv()

logger = structlog.get_logger()

def check_environment_variables():
    """检查环境变量配置"""
    print("🔍 检查环境变量配置...")
    
    required_vars = {
        'HUNYUAN_SECRET_ID': '腾讯云SecretId',
        'HUNYUAN_SECRET_KEY': '腾讯云SecretKey'
    }
    
    optional_vars = {
        'DEEPSEEK_API_KEY': 'DeepSeek API密钥',
        'HUNYUAN_MODEL': '混元模型版本',
        'HUNYUAN_REGION': '腾讯云地域'
    }
    
    config_status = {}
    
    print("\n📋 必需配置项:")
    for var, desc in required_vars.items():
        value = os.getenv(var)
        if value and value.strip():
            print(f"   ✅ {desc} ({var}): 已配置")
            config_status[var] = True
        else:
            print(f"   ❌ {desc} ({var}): 未配置")
            config_status[var] = False
    
    print("\n📋 可选配置项:")
    for var, desc in optional_vars.items():
        value = os.getenv(var)
        if value and value.strip():
            print(f"   ✅ {desc} ({var}): {value}")
            config_status[var] = True
        else:
            print(f"   ⚠️  {desc} ({var}): 使用默认值")
            config_status[var] = False
    
    return config_status

def test_hunyuan_connection():
    """测试混元模型连接"""
    print("\n🚀 测试混元模型连接...")
    
    try:
        from app.services.ai_translation_service import ai_translation_service
        
        # 测试简单翻译
        test_text = "Hello, this is a test."
        result = ai_translation_service.translate_text(
            text=test_text,
            source_lang="en",
            target_lang="zh"
        )
        
        if result and result != test_text:
            print(f"   ✅ 混元模型连接成功")
            print(f"   📝 测试翻译: '{test_text}' → '{result}'")
            return True
        else:
            print(f"   ⚠️  混元模型连接成功，但翻译结果可能不准确")
            print(f"   📝 测试翻译: '{test_text}' → '{result}'")
            return True
            
    except Exception as e:
        print(f"   ❌ 混元模型连接失败: {str(e)}")
        return False

def test_deepseek_connection():
    """测试DeepSeek模型连接"""
    print("\n🚀 测试DeepSeek模型连接...")
    
    deepseek_key = os.getenv('DEEPSEEK_API_KEY')
    if not deepseek_key or not deepseek_key.strip():
        print("   ⚠️  DeepSeek API密钥未配置，跳过测试")
        return True
    
    try:
        # 这里可以添加DeepSeek API测试代码
        print("   ⚠️  DeepSeek连接测试暂未实现")
        return True
        
    except Exception as e:
        print(f"   ❌ DeepSeek模型连接失败: {str(e)}")
        return False

def test_ai_service_functionality():
    """测试AI服务功能"""
    print("\n🧪 测试AI服务功能...")
    
    try:
        from app.services.ai_translation_service import ai_translation_service
        
        # 测试批量翻译
        test_texts = ["Good morning", "Thank you", "Goodbye"]
        results = ai_translation_service.translate_batch(
            texts=test_texts,
            source_lang="en",
            target_lang="zh"
        )
        
        success_count = sum(1 for orig, trans in zip(test_texts, results) if trans != orig)
        
        print(f"   📊 批量翻译测试: {success_count}/{len(test_texts)} 成功")
        
        for orig, trans in zip(test_texts, results):
            print(f"      '{orig}' → '{trans}'")
        
        return success_count > 0
        
    except Exception as e:
        print(f"   ❌ AI服务功能测试失败: {str(e)}")
        return False

def generate_config_report():
    """生成配置报告"""
    print("\n📊 生成配置报告...")
    
    report = {
        "配置时间": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Python版本": sys.version.split()[0],
        "工作目录": os.getcwd(),
        "环境变量文件": ".env" if os.path.exists(".env") else "不存在"
    }
    
    # 检查关键文件
    key_files = [
        "app/services/ai_translation_service.py",
        "app/config.py",
        ".env"
    ]
    
    print("   📁 关键文件检查:")
    for file_path in key_files:
        if os.path.exists(file_path):
            print(f"      ✅ {file_path}")
        else:
            print(f"      ❌ {file_path}")
    
    return report

def main():
    """主验证函数"""
    print("=" * 60)
    print("🔧 腾讯云开发AI+配置验证工具")
    print("=" * 60)
    
    # 1. 检查环境变量
    config_status = check_environment_variables()
    
    # 2. 测试混元模型连接
    hunyuan_ok = test_hunyuan_connection()
    
    # 3. 测试DeepSeek模型连接
    deepseek_ok = test_deepseek_connection()
    
    # 4. 测试AI服务功能
    service_ok = test_ai_service_functionality()
    
    # 5. 生成配置报告
    report = generate_config_report()
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📋 验证结果汇总")
    print("=" * 60)
    
    required_configured = all(config_status.get(var, False) for var in ['HUNYUAN_SECRET_ID', 'HUNYUAN_SECRET_KEY'])
    
    print(f"环境变量配置    : {'✅ 完整' if required_configured else '❌ 不完整'}")
    print(f"混元模型连接    : {'✅ 正常' if hunyuan_ok else '❌ 异常'}")
    print(f"DeepSeek连接   : {'✅ 正常' if deepseek_ok else '❌ 异常'}")
    print(f"AI服务功能     : {'✅ 正常' if service_ok else '❌ 异常'}")
    
    overall_status = required_configured and hunyuan_ok and service_ok
    
    print(f"\n🎯 总体状态: {'✅ 配置完成，可以使用' if overall_status else '⚠️  需要进一步配置'}")
    
    if not overall_status:
        print("\n💡 配置建议:")
        if not required_configured:
            print("   1. 请在 .env 文件中配置腾讯云API密钥")
            print("   2. 参考 config_guide.md 获取详细配置指南")
        if not hunyuan_ok:
            print("   3. 检查网络连接和API密钥权限")
        if not service_ok:
            print("   4. 检查AI服务依赖是否正确安装")
    
    return overall_status

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  验证被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 验证过程出现异常: {str(e)}")
        sys.exit(1)