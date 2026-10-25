# 樹莓派設定網路 IP 給 CNC 控制器使用

import ipaddress
import os
import shutil
import subprocess
import sys
import logging
from config import ConfigManager

logger = logging.getLogger(__name__)

class CNCNetworkManager:
    def __init__(self, config_manager: ConfigManager):
        # 初始化 CNC 網路管理器，載入配置管理
        self.config = config_manager

    def select_host_ip(self, cnc_ip, prefix_length=24):
        """
        根據 CNC IP 自動選擇主機 IP。
        預設選擇網段最後一個可用位址，避免與 CNC IP、網路位址及廣播位址衝突。
        """
        if not 1 <= prefix_length <= 30:
            logger.error("網路前綴必須介於 1 到 30")
        
        cnc_ip = ipaddress.IPv4Address(str(cnc_ip).strip())
        network = ipaddress.IPv4Network(f"{cnc_ip}/{prefix_length}", strict=False)

        if (cnc_ip in (network.network_address, network.broadcast_address)
            or cnc_ip.is_multicast or cnc_ip.is_loopback or cnc_ip.is_unspecified):
            logger.error(f"無效的 CNC IP: {cnc_ip}")
        
        host_ip = ipaddress.IPv4Address(int(network.broadcast_address) - 1)

        if host_ip == cnc_ip:
            host_ip = ipaddress.IPv4Address(int(host_ip) - 1)
            print(f"[*] CNC IP 與自動選擇的主機 IP 衝突，改為使用: {host_ip}")

        if host_ip not in network:
            logger.error(f"主機 IP {host_ip} 不在 CNC 網段 {network}")

        if host_ip in (cnc_ip, network.network_address, network.broadcast_address):
            logger.error("主機 IP 與 CNC 或保留位址衝突")

        return str(host_ip)

    def run_nmcli(self, arguments):
        """
        執行 NetworkManager 設定。

        sudo -n：非互動模式，不要求終端機輸入密碼。
        執行帳號需事先具有網路設定權限。
        """

        command = ["nmcli", *arguments]
        logger.info(f"執行命令: {command}")

        if os.geteuid() != 0:
            command = ["sudo", "-n", *command]

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            return result.stdout.strip()

        except subprocess.CalledProcessError as e:
            error = (e.stderr or e.stdout or str(e)).strip()
            logger.error(f"nmcli 設定失敗: {error}")

        except subprocess.TimeoutExpired as e:
            logger.error(f"nmcli 執行逾時: {e}")

    def configure_network(self):
        """
        自動設定 Raspberry Pi 的 CNC 有線網路。

        Parameters
        ----------
        cnc_ip : str
            CNC 控制器 IP

        connection : str
            NetworkManager 連線名稱

        prefix_length : int
            子網路前綴，預設 /24

        target_ip : str | None
            手動指定本機 IP，None 表示自動選擇

        Returns
        -------
        str
            Raspberry Pi 設定的本機 IP
        """
        try:
            # 讀取 CNC 網路設定
            cnc_ip = self.config.CNC_IP
            connection = self.config.CNC_CONNECTION
            prefix_length = 24  # 固定使用 /24 子網路
            host_ip = self.select_host_ip(cnc_ip, prefix_length=prefix_length)

            logger.info(f"[Raspberry Pi] CNC IP: {cnc_ip}")
            logger.info(f"[Raspberry Pi] Host IP: {host_ip}/{prefix_length}")
            logger.info(f"[Raspberry Pi] Connection: {connection}")

            # 檢查作業系統
            if not sys.platform.startswith("linux"):
                logger.error("只支援 Linux NetworkManager")

            if not shutil.which("nmcli"):
                logger.error("找不到 nmcli")

            if os.geteuid() != 0 and not shutil.which("sudo"):
                logger.error("找不到 sudo")

            # 修改網卡設定
            self.run_nmcli([
                "connection", "modify", connection,
                "ipv4.method", "manual",
                "ipv4.addresses", f"{host_ip}/{prefix_length}",
                "ipv4.gateway", "",
                "ipv4.never-default", "yes",
                "ipv4.route-metric", "50",
                "connection.autoconnect", "yes",
                "connection.autoconnect-priority", "0"
            ])

            # 重新啟用連線，使新 IP 生效
            self.run_nmcli(["connection", "up", connection])

            logger.info("[Raspberry Pi] CNC network configured successfully")

            return host_ip

        except Exception as e:
            logger.error(f"[Raspberry Pi] CNC 網路設定失敗: {e}")

if __name__ == "__main__":
    # 測試 CNCNetworkManager
    config_manager = ConfigManager()
    cnc_network_manager = CNCNetworkManager(config_manager)

    try:
        host_ip = cnc_network_manager.configure_network()
        logger.info(f"Raspberry Pi 設定的本機 IP: {host_ip}")
    except Exception as e:
        logger.error(f"網路設定測試失敗: {e}")