import requests

def test_translation_service(base_url="http://localhost:8989", token=None):
    headers = {"Authorization": token} if token else {}
    
    # 测试服务状态
    try:
        # 测试健康检查
        health = requests.get(f"{base_url}/health", timeout=5)
        print(f"健康检查: {health.status_code} - {health.text}")
        
        # 测试版本信息
        version = requests.get(f"{base_url}/version", timeout=5)
        print(f"服务版本: {version.json() if version.ok else '获取失败'}")
        
        # 测试语言对
        models = requests.get(f"{base_url}/models", headers=headers, timeout=5)
        print(f"支持的语言对: {models.json() if models.ok else '获取失败'}")
        
        # 测试单条翻译
        payload = {
            "from": "en",
            "to": "zh",
            "text": "Hello, world! This is a test."
        }
        trans = requests.post(
            f"{base_url}/translate",
            json=payload,
            headers=headers,
            timeout=10
        )
        if trans.ok:
            print(f"翻译测试: {payload['text']} -> {trans.json()['result']}")
        else:
            print(f"翻译失败: {trans.status_code} - {trans.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"连接翻译服务失败: {str(e)}")
        print("请确认：")
        print("1. Docker 容器是否正在运行")
        print("2. 端口 8989 是否正确映射")
        print(f"3. 服务地址是否正确: {base_url}")

if __name__ == "__main__":
    # 替换为你的 token，如果不需要认证可以设为 None
    TOKEN = "your_token_here"  # 修改这里
    test_translation_service(token=TOKEN)