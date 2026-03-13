#!/usr/bin/env python3
"""
依赖库自动检测与安装脚本

功能：自动检测并安装运行 house_reps_scraper.py 所需的所有依赖库
"""

import subprocess
import sys
import importlib.util

def check_module(module_name, package_name=None):
    """
    检查模块是否已安装
    
    Args:
        module_name: 导入时使用的模块名（如 'bs4'）
        package_name: pip安装时使用的包名（如 'beautifulsoup4'），如果与module_name不同
    
    Returns:
        bool: 模块是否已安装
    """
    if package_name is None:
        package_name = module_name
    
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return False, package_name
    return True, package_name

def install_package(package_name):
    """
    使用pip安装指定的包
    
    Args:
        package_name: 要安装的包名
    
    Returns:
        bool: 安装是否成功
    """
    print(f"正在安装 {package_name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"✓ {package_name} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {package_name} 安装失败: {e}")
        return False

def main():
    """主函数：检测并安装所有依赖"""
    print("=" * 50)
    print("依赖库自动检测与安装")
    print("=" * 50)
    
    # 定义需要检查的依赖
    # 格式: (模块导入名, pip包名) - 如果相同，pip包名可以为None
    dependencies = [
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),  # 导入用bs4，安装用beautifulsoup4
        ("pandas", "pandas"),
        ("openpyxl", "openpyxl"),   # pandas保存Excel需要
    ]
    
    all_installed = True
    need_install = []
    
    # 第一步：检测哪些库未安装
    print("\n【1/2】检测依赖库状态...")
    print("-" * 50)
    
    for module_name, package_name in dependencies:
        installed, pkg_name = check_module(module_name, package_name)
        if installed:
            print(f"✓ {module_name:15} 已安装")
        else:
            print(f"✗ {module_name:15} 未安装 (需要安装: {pkg_name})")
            need_install.append(pkg_name)
            all_installed = False
    
    # 第二步：安装缺失的库
    if need_install:
        print("\n【2/2】安装缺失的依赖库...")
        print("-" * 50)
        
        for pkg in need_install:
            success = install_package(pkg)
            if not success:
                all_installed = False
    else:
        print("\n【2/2】所有依赖库均已安装，无需操作")
    
    # 总结
    print("\n" + "=" * 50)
    if all_installed:
        print("✓ 所有依赖库准备就绪！")
        print("=" * 50)
        return 0
    else:
        print("✗ 部分依赖库安装失败，请检查网络连接或手动安装")
        print("=" * 50)
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
