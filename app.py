# app.py (نسخة محسّنة احترافية - Production Ready)
import os
import json
import re
import subprocess
import psutil
import socket
import sys
import hashlib
import secrets
import time
import threading
import requests
import shutil
import zipfile
import signal
import logging
import gc
import fcntl  # لقفل الملفات على Linux
from datetime import datetime, timedelta
from functools import lru_cache, wraps
from threading import Lock, Semaphore, Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, send_from_directory, request, jsonify, session, redirect, make_response

# ==================== إعداد المسارات الأساسية ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "USERS")
os.makedirs(USERS_DIR, exist_ok=True)

# ==================== إعدادات التطبيق المحسّنة ====================
class Config:
    """تكوين مركزي للتطبيق"""
    SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))  # مفتاح عشوائي آمن
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False  # True في production مع HTTPS
    
    # حدود الموارد
    MAX_WORKERS = 10  # الحد الأقصى للخيوط المتوازية
    DB_WRITE_BATCH_INTERVAL = 2.0  # تجميع عمليات الكتابة كل ثانيتين
    LOG_MAX_SIZE_MB = 50  # الحد الأقصى لحجم ملف السجل
    LOG_BACKUP_COUNT = 2  # عدد النسخ الاحتياطية للسجلات
    PROCESS_MONITOR_INTERVAL = 10  # مراقبة العمليات كل 10 ثواني
    ZOMBIE_CLEANUP_INTERVAL = 60  # تنظيف العمليات الميتة كل دقيقة
    PORT_SCAN_TIMEOUT = 0.05  # مهلة فحص المنافذ
    CACHE_TTL = 30  # مدة صلاحية الكاش بالثواني

app = Flask(__name__, static_folder=BASE_DIR)
app.config.from_object(Config())
app.secret_key = Config.SECRET_KEY

# ==================== إعداد نظام التسجيل المحسّن ====================
def setup_logging():
    """إعداد نظام تسجيل احترافي مع تدوير السجلات"""
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # ملف السجل الرئيسي مع تدوير تلقائي
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        os.path.join(BASE_DIR, 'app.log'),
        maxBytes=Config.LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=Config.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.WARNING)
    
    # سجل الكونسول للتطوير
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)
    
    # تكوين السجل الرئيسي
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.INFO)

setup_logging()

# ==================== نظام التخزين المؤقت المحسّن ====================
class SimpleCache:
    """نظام تخزين مؤقت بسيط مع TTL"""
    def __init__(self, ttl=Config.CACHE_TTL):
        self._cache = {}
        self._lock = Lock()
        self._ttl = ttl
    
    def get(self, key):
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self._ttl:
                    return value
                else:
                    del self._cache[key]
        return None
    
    def set(self, key, value):
        with self._lock:
            self._cache[key] = (value, time.time())
    
    def clear(self):
        with self._lock:
            self._cache.clear()

# كاش للاستعلامات المتكررة
db_cache = SimpleCache()
metrics_cache = SimpleCache(ttl=5)  # كاش أسرع للمقاييس

# ==================== إدارة الخيوط المحسّنة ====================
class ThreadPoolManager:
    """مدير تجمع الخيوط لمنع تسريبات الذاكرة"""
    def __init__(self, max_workers=Config.MAX_WORKERS):
        self._executor = None
        self._lock = Lock()
        self._max_workers = max_workers
        self._active_threads = set()
    
    @property
    def executor(self):
        if self._executor is None:
            with self._lock:
                if self._executor is None:  # Double-check locking
                    self._executor = ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix="Worker"
                    )
        return self._executor
    
    def submit_task(self, fn, *args, **kwargs):
        """تقديم مهمة للتجمع مع تتبع الخيوط النشطة"""
        future = self.executor.submit(fn, *args, **kwargs)
        self._active_threads.add(future)
        future.add_done_callback(self._active_threads.discard)
        return future
    
    def shutdown(self):
        """إغلاق التجمع بشكل آمن"""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

# إنشاء تجمع خيوط عالمي
thread_pool = ThreadPoolManager()

# ===================== بيانات المسؤول ====================
ADMIN_USERNAME = "NASSIMHz123"
ADMIN_PASSWORD_RAW = os.environ.get("ADMIN_PASSWORD", "NASSIMHZGG123")

# ===================== إعدادات البوت والإشعارات ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8676528994:AAFFbhvKNTAoElHYx0pzpT3TaLZxUE3b0js")
ADMIN_TELEGRAM_ID = int(os.environ.get("TELEGRAM_ID", "7092182498"))
ADMIN_TELEGRAM_USERNAME = "@NASSIM_D5X"

# ===================== نظام الإشعارات المحسّن ====================
class NotificationManager:
    """مدير الإشعارات مع إعادة المحاولة والتحكم في المعدل"""
    def __init__(self):
        self._last_notification_time = 0
        self._notification_cooldown = 1.0  # تبريد بين الإشعارات
        self._lock = Lock()
        self._session = requests.Session()
        self._session.headers.update({
            'Connection': 'keep-alive',
            'User-Agent': 'NASSIM-HOST/2.0'
        })
    
    def send(self, message: str, retries=2):
        """إرسال إشعار مع إعادة المحاولة"""
        with self._lock:
            current_time = time.time()
            if current_time - self._last_notification_time < self._notification_cooldown:
                # تأخير الإشعار إذا كان هناك تبريد نشط
                time.sleep(self._notification_cooldown)
            
            for attempt in range(retries):
                try:
                    response = self._session.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                        json={
                            "chat_id": ADMIN_TELEGRAM_ID,
                            "text": message,
                            "parse_mode": "Markdown"
                        },
                        timeout=5
                    )
                    if response.status_code == 200:
                        self._last_notification_time = time.time()
                        return True
                except Exception:
                    if attempt < retries - 1:
                        time.sleep(1)
            return False

notifier = NotificationManager()

def notify_admin(message: str):
    """إرسال إشعار للأدمن بشكل غير متزامن"""
    thread_pool.submit_task(notifier.send, message)

# ===================== قاعدة البيانات المحسّنة ====================
DB_FILE = os.path.join(BASE_DIR, "db.json")
DB_BACKUP_DIR = os.path.join(BASE_DIR, "db_backups")

class Database:
    """نظام قاعدة بيانات محسّن مع قفل وأمان"""
    def __init__(self):
        self._lock = Lock()
        self._write_semaphore = Semaphore(1)  # منع الكتابة المتزامنة
        self._pending_writes = 0
        self._last_write_time = 0
        self._write_timer = None
        self._in_transaction = False
        
        # إنشاء نسخة احتياطية تلقائية
        os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    
    def load(self):
        """تحميل قاعدة البيانات مع معالجة الأخطاء المحسّنة"""
        cache_key = "db_data"
        cached = db_cache.get(cache_key)
        if cached is not None:
            return cached.copy()  # نسخة لتجنب التعديل المباشر
        
        with self._lock:
            if os.path.exists(DB_FILE):
                for attempt in range(3):  # 3 محاولات
                    try:
                        with open(DB_FILE, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        # تأكد من وجود الحقول الجديدة
                        if "plans" not in data:
                            data["plans"] = {}
                        self._create_backup()  # نسخة احتياطية تلقائية
                        db_cache.set(cache_key, data)
                        return data
                    except json.JSONDecodeError:
                        app.logger.error(f"محاولة {attempt + 1}: فشل قراءة DB - ملف تالف")
                        if attempt < 2:
                            # محاولة استعادة من نسخة احتياطية
                            backup_data = self._restore_from_backup()
                            if backup_data:
                                return backup_data
                            time.sleep(1)
                    except Exception as e:
                        app.logger.error(f"خطأ غير متوقع في قراءة DB: {e}")
                        break
            
            # إنشاء قاعدة بيانات افتراضية
            return self._create_default_db()
    
    def _create_default_db(self):
        """إنشاء قاعدة بيانات افتراضية"""
        admin_hash = hashlib.sha256(ADMIN_PASSWORD_RAW.encode()).hexdigest()
        default_db = {
            "users": {
                ADMIN_USERNAME: {
                    "password": admin_hash,
                    "is_admin": True,
                    "created_at": str(datetime.now()),
                    "max_servers": 999999,
                    "expiry_days": 3650,
                    "last_login": None,
                    "telegram_id": None,
                    "api_key": None,
                    "storage_limit": 10240,
                    "plan": "admin"
                }
            },
            "servers": {},
            "logs": [],
            "plans": {
                "free": {"name": "🎁 مجاني", "storage": 512000, "ram": 256, "cpu": 0.5, "max_servers": 2, "price": 0},
                "4gb": {"name": "💎 4 جيجا", "storage": 4096000, "ram": 1024, "cpu": 1, "max_servers": 5, "price": 5},
                "10gb": {"name": "💎 10 جيجا", "storage": 10240000, "ram": 2048, "cpu": 2, "max_servers": 10, "price": 10},
                "40gb": {"name": "💎 40 جيجا", "storage": 40960000, "ram": 4096, "cpu": 4, "max_servers": 20, "price": 25}
            }
        }
        return default_db
    
    def save(self, data, immediate=False):
        """حفظ قاعدة البيانات مع تجميع الكتابات"""
        with self._lock:
            db_cache.set("db_data", data)
            
            if immediate:
                self._write_to_disk(data)
            else:
                # تجميع الكتابات لتقليل الضغط على القرص
                self._pending_writes += 1
                current_time = time.time()
                
                if current_time - self._last_write_time >= Config.DB_WRITE_BATCH_INTERVAL:
                    self._write_to_disk(data)
                elif self._pending_writes >= 10:  # كتابة فورية إذا تجمعت 10 عمليات
                    self._write_to_disk(data)
                else:
                    # جدولة كتابة مؤجلة
                    if self._write_timer is None:
                        self._write_timer = threading.Timer(
                            Config.DB_WRITE_BATCH_INTERVAL,
                            self._flush_writes
                        )
                        self._write_timer.start()
    
    def _flush_writes(self):
        """تنفيذ الكتابات المؤجلة"""
        with self._lock:
            if self._pending_writes > 0:
                data = db_cache.get("db_data")
                if data:
                    self._write_to_disk(data)
                self._pending_writes = 0
            self._write_timer = None
    
    def _write_to_disk(self, data):
        """كتابة البيانات على القرص بشكل آمن"""
        temp_file = DB_FILE + '.tmp'
        try:
            # كتابة لملف مؤقت أولاً
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # ضمان الكتابة على القرص
            
            # استبدال الملف الأصلي بالملف المؤقت (عملية ذرية)
            if os.name == 'posix':
                os.replace(temp_file, DB_FILE)
            else:
                if os.path.exists(DB_FILE):
                    os.remove(DB_FILE)
                os.rename(temp_file, DB_FILE)
            
            self._last_write_time = time.time()
            self._pending_writes = 0
            
        except Exception as e:
            app.logger.error(f"فشل كتابة DB: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
    def _create_backup(self):
        """إنشاء نسخة احتياطية من قاعدة البيانات"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(DB_BACKUP_DIR, f"db_backup_{timestamp}.json")
            shutil.copy2(DB_FILE, backup_path)
            
            # الاحتفاظ بآخر 5 نسخ احتياطية فقط
            backups = sorted(os.listdir(DB_BACKUP_DIR))
            while len(backups) > 5:
                os.remove(os.path.join(DB_BACKUP_DIR, backups[0]))
                backups.pop(0)
        except Exception as e:
            app.logger.error(f"فشل إنشاء نسخة احتياطية: {e}")
    
    def _restore_from_backup(self):
        """محاولة استعادة قاعدة البيانات من نسخة احتياطية"""
        try:
            backups = sorted(os.listdir(DB_BACKUP_DIR), reverse=True)
            for backup in backups:
                backup_path = os.path.join(DB_BACKUP_DIR, backup)
                with open(backup_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # استعادة ناجحة
                with open(DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                app.logger.info(f"تم استعادة DB من النسخة الاحتياطية: {backup}")
                return data
        except Exception as e:
            app.logger.error(f"فشل استعادة النسخة الاحتياطية: {e}")
        return None

# إنشاء مدير قاعدة البيانات العالمي
db_manager = Database()

def load_db():
    """تحميل قاعدة البيانات (واجهة متوافقة مع الكود القديم)"""
    return db_manager.load()

def save_db(db_data, immediate=False):
    """حفظ قاعدة البيانات (واجهة متوافقة مع الكود القديم)"""
    db_manager.save(db_data, immediate)
    return True

# تحميل قاعدة البيانات الأولي
db = load_db()

# ===================== نظام المنافذ المحسّن ====================
PORT_RANGE_START = 8100
PORT_RANGE_END = 9100

class PortManager:
    """مدير المنافذ مع تخزين مؤقت"""
    def __init__(self):
        self._lock = Lock()
        self._used_ports = set()
        self._port_cache = {}  # تخزين مؤقت للمنافذ المخصصة
        self._initialize_used_ports()
    
    def _initialize_used_ports(self):
        """تهيئة قائمة المنافذ المستخدمة"""
        for srv in db.get("servers", {}).values():
            if srv.get("port"):
                self._used_ports.add(srv["port"])
    
    def get_available_port(self):
        """الحصول على منفذ متاح بشكل سريع"""
        with self._lock:
            # تحديث المنافذ المستخدمة من العمليات النشطة
            for port in list(self._used_ports):
                if not self._is_port_in_use(port):
                    self._used_ports.discard(port)
            
            # البحث عن منفذ متاح
            for port in range(PORT_RANGE_START, PORT_RANGE_END):
                if port not in self._used_ports:
                    if not self._is_port_in_use(port):
                        self._used_ports.add(port)
                        return port
            
            return PORT_RANGE_START
    
    def _is_port_in_use(self, port):
        """فحص ما إذا كان المنفذ مستخدم"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(Config.PORT_SCAN_TIMEOUT)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except Exception:
            return True
    
    def release_port(self, port):
        """تحرير منفذ"""
        with self._lock:
            self._used_ports.discard(port)

port_manager = PortManager()

def get_assigned_port():
    """الحصول على منفذ مخصص (واجهة متوافقة مع الكود القديم)"""
    return port_manager.get_available_port()

# ===================== نظام العمليات المحسّن ====================
class ProcessManager:
    """مدير العمليات مع مراقبة ذكية"""
    def __init__(self):
        self._lock = Lock()
        self._monitoring_active = False
        self._monitor_thread = None
        self._zombie_cleaner_thread = None
    
    def start_process(self, folder):
        """بدء عملية سيرفر"""
        srv = db["servers"].get(folder)
        if not srv:
            return False, "السيرفر غير موجود"
        
        server_type = srv.get("type", "Python")
        main_file = srv.get("startup_file", "")
        
        if not main_file:
            main_file = detect_main_file(srv["path"], server_type)
            if main_file:
                srv["startup_file"] = main_file
                save_db(db, immediate=True)
            else:
                return False, f"لا يوجد ملف تشغيل {'Python (.py)' if server_type == 'Python' else 'Node.js (.js)'}"
        
        file_path = os.path.join(srv["path"], main_file)
        if not os.path.exists(file_path):
            return False, f"الملف '{main_file}' غير موجود"
        
        port = srv.get("port") or port_manager.get_available_port()
        srv["port"] = port
        
        # إعداد ملفات السجل مع تدوير
        log_path = os.path.join(srv["path"], "out.log")
        error_path = os.path.join(srv["path"], "errors.log")
        
        # تدوير السجلات إذا كانت كبيرة جداً
        self._rotate_log_if_needed(log_path)
        self._rotate_log_if_needed(error_path)
        
        with open(log_path, "a", encoding='utf-8') as log_file:
            log_file.write(
                f"\n{'='*50}\n🚀 بدء التشغيل - {datetime.now()}\n"
                f"📁 {main_file}\n🔌 المنفذ: {port}\n🏷 النوع: {server_type}\n{'='*50}\n\n"
            )
        
        try:
            env = os.environ.copy()
            env["PORT"] = str(port)
            env["SERVER_PORT"] = str(port)
            
            cmd = ["node", main_file] if server_type == "Node.js" else [sys.executable, "-u", main_file]
            
            # فتح ملفات الإخراج
            stdout_file = open(log_path, "a", encoding='utf-8')
            stderr_file = open(error_path, "a", encoding='utf-8')
            
            proc = subprocess.Popen(
                cmd,
                cwd=srv["path"],
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            
            srv["status"] = "Running"
            srv["pid"] = proc.pid
            srv["start_time"] = time.time()
            save_db(db, immediate=True)
            
            # بدء المراقبة إذا لم تكن نشطة
            self._ensure_monitoring()
            
            return True, "✅ تم التشغيل"
            
        except FileNotFoundError:
            err = f"❌ المشغّل غير موجود: {'node' if server_type == 'Node.js' else 'python'}"
            app.logger.error(err)
            return False, err
        except Exception as e:
            app.logger.error(f"خطأ في بدء العملية: {e}")
            return False, str(e)
    
    def stop_process(self, folder):
        """إيقاف عملية سيرفر مع تنظيف العمليات الفرعية"""
        srv = db["servers"].get(folder)
        if not srv:
            return
        
        pid = srv.get("pid")
        if pid:
            try:
                # محاولة إنهاء العملية بشكل نظيف
                self._kill_process_tree(pid)
            except Exception as e:
                app.logger.error(f"خطأ في إيقاف العملية {pid}: {e}")
        
        srv["status"] = "Stopped"
        srv["pid"] = None
        
        # تحرير المنفذ
        if srv.get("port"):
            port_manager.release_port(srv["port"])
        
        save_db(db, immediate=True)
    
    def _kill_process_tree(self, pid):
        """قتل شجرة العمليات بشكل كامل"""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            # قتل الأطفال أولاً
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # انتظار انتهاء الأطفال
            gone, alive = psutil.wait_procs(children, timeout=3)
            
            # قتل العمليات المتبقية
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
            
            # قتل العملية الأم
            parent.terminate()
            parent.wait(timeout=3)
            
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            # محاولة killpg كحل أخير
            try:
                os.killpg(pid, signal.SIGKILL)
            except:
                pass
    
    def _rotate_log_if_needed(self, log_path, max_size=Config.LOG_MAX_SIZE_MB * 1024 * 1024):
        """تدوير ملف السجل إذا تجاوز الحجم المحدد"""
        try:
            if os.path.exists(log_path) and os.path.getsize(log_path) > max_size:
                backup_path = log_path + '.1'
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.rename(log_path, backup_path)
        except Exception:
            pass
    
    def _ensure_monitoring(self):
        """ضمان تشغيل نظام المراقبة"""
        if not self._monitoring_active:
            self._monitoring_active = True
            self._monitor_thread = threading.Thread(
                target=self._process_monitor_loop,
                daemon=True,
                name="ProcessMonitor"
            )
            self._monitor_thread.start()
            
            self._zombie_cleaner_thread = threading.Thread(
                target=self._zombie_cleaner_loop,
                daemon=True,
                name="ZombieCleaner"
            )
            self._zombie_cleaner_thread.start()
    
    def _process_monitor_loop(self):
        """حلقة مراقبة العمليات المحسّنة"""
        app.logger.info("بدء نظام مراقبة العمليات")
        
        while self._monitoring_active:
            try:
                # نسخة محلية من الخوادم لتجنب القفل المطول
                servers_snapshot = dict(db.get("servers", {}))
                
                for folder, srv in servers_snapshot.items():
                    if srv.get("status") == "Running":
                        self._check_and_restart_process(folder, srv)
                
                # جمع القمامة بشكل دوري
                gc.collect()
                
            except Exception as e:
                app.logger.error(f"خطأ في مراقبة العمليات: {e}")
            
            time.sleep(Config.PROCESS_MONITOR_INTERVAL)
    
    def _check_and_restart_process(self, folder, srv):
        """فحص وإعادة تشغيل عملية إذا لزم الأمر"""
        pid = srv.get("pid")
        if not pid:
            return
        
        try:
            process = psutil.Process(pid)
            
            # فحص حالة العملية
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                app.logger.warning(f"العملية {pid} ({folder}) ميتة - إعادة تشغيل")
                self.restart_server(folder)
            else:
                # فحص استهلاك الموارد
                try:
                    memory_percent = process.memory_percent()
                    if memory_percent > 90:  # استهلاك ذاكرة خطير
                        app.logger.warning(
                            f"استهلاك ذاكرة عالي {memory_percent:.1f}% للسيرفر {folder}"
                        )
                except:
                    pass
                
        except psutil.NoSuchProcess:
            app.logger.warning(f"العملية {pid} ({folder}) غير موجودة - إعادة تشغيل")
            self.restart_server(folder)
        except Exception as e:
            app.logger.error(f"خطأ في فحص العملية {folder}: {e}")
    
    def _zombie_cleaner_loop(self):
        """تنظيف العمليات الميتة بشكل دوري"""
        app.logger.info("بدء نظام تنظيف العمليات الميتة")
        
        while self._monitoring_active:
            try:
                # تنظيف العمليات الميتة
                for proc in psutil.process_iter(['pid', 'status']):
                    try:
                        if proc.info['status'] == psutil.STATUS_ZOMBIE:
                            proc.wait(timeout=1)
                    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                        pass
                
            except Exception as e:
                app.logger.error(f"خطأ في تنظيف العمليات الميتة: {e}")
            
            time.sleep(Config.ZOMBIE_CLEANUP_INTERVAL)
    
    def restart_server(self, folder):
        """إعادة تشغيل سيرفر"""
        self.stop_process(folder)
        time.sleep(1)  # انتظار قصير للتنظيف
        return self.start_process(folder)
    
    def cleanup_all(self):
        """تنظيف جميع العمليات عند إغلاق التطبيق"""
        self._monitoring_active = False
        for folder in list(db.get("servers", {}).keys()):
            self.stop_process(folder)

# إنشاء مدير العمليات العالمي
proc_manager = ProcessManager()

# ===================== دوال كشف الملفات المحسّنة ====================
@lru_cache(maxsize=100)
def detect_main_file(srv_path: str, server_type: str) -> str:
    """يكشف ملف التشغيل الرئيسي تلقائياً (مع تخزين مؤقت)"""
    if not os.path.exists(srv_path):
        return ""
    
    try:
        if server_type == "Node.js":
            return _detect_node_main(srv_path)
        else:
            return _detect_python_main(srv_path)
    except Exception as e:
        app.logger.error(f"خطأ في كشف الملف الرئيسي: {e}")
        return ""

def _detect_node_main(srv_path):
    """كشف ملف Node.js الرئيسي"""
    pkg = os.path.join(srv_path, "package.json")
    if os.path.exists(pkg):
        try:
            with open(pkg, 'r', encoding='utf-8') as f:
                data = json.load(f)
            main = data.get("main", "")
            if main and os.path.exists(os.path.join(srv_path, main)):
                return main
            scripts = data.get("scripts", {})
            start_cmd = scripts.get("start", "")
            m = re.search(r'node\s+(\S+\.js)', start_cmd)
            if m and os.path.exists(os.path.join(srv_path, m.group(1))):
                return m.group(1)
        except Exception:
            pass
    
    for candidate in ["index.js", "bot.js", "app.js", "main.js", "server.js"]:
        if os.path.exists(os.path.join(srv_path, candidate)):
            return candidate
    
    js_files = [f for f in os.listdir(srv_path) if f.endswith('.js')]
    return js_files[0] if js_files else ""

def _detect_python_main(srv_path):
    """كشف ملف Python الرئيسي"""
    for candidate in ["main.py", "bot.py", "app.py", "index.py", "run.py", "start.py"]:
        if os.path.exists(os.path.join(srv_path, candidate)):
            return candidate
    
    py_files = [f for f in os.listdir(srv_path) if f.endswith('.py')]
    return py_files[0] if py_files else ""

# ===================== تثبيت المكتبات المحسّن ====================
def auto_install_deps(srv_path: str, server_type: str, log_file):
    """تثبيت تلقائي للمكتبات مع timeout محسّن"""
    try:
        if server_type == "Node.js":
            pkg = os.path.join(srv_path, "package.json")
            if os.path.exists(pkg):
                log_file.write(f"\n📦 تثبيت node_modules...\n")
                log_file.flush()
                proc = subprocess.Popen(
                    ["npm", "install", "--prefer-offline"],
                    cwd=srv_path,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=os.environ.copy()
                )
                proc.wait(timeout=120)
                log_file.write("✅ تم تثبيت node_modules\n")
        else:
            req = os.path.join(srv_path, "requirements.txt")
            if os.path.exists(req):
                log_file.write(f"\n📦 تثبيت requirements.txt...\n")
                log_file.flush()
                proc = subprocess.Popen(
                    [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", "requirements.txt"],
                    cwd=srv_path,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=os.environ.copy()
                )
                proc.wait(timeout=180)
                log_file.write("✅ تم تثبيت المكتبات\n")
    except subprocess.TimeoutExpired:
        log_file.write("\n⚠️ انتهت مهلة التثبيت\n")
    except Exception as e:
        log_file.write(f"\n⚠️ تثبيت تلقائي: {e}\n")
    log_file.flush()

# ===================== واجهات متوافقة مع الكود القديم ====================
def start_server_process(folder):
    """بدء عملية سيرفر (واجهة متوافقة)"""
    return proc_manager.start_process(folder)

def stop_server_process(folder):
    """إيقاف عملية سيرفر (واجهة متوافقة)"""
    proc_manager.stop_process(folder)

def restart_server(folder):
    """إعادة تشغيل سيرفر (واجهة متوافقة)"""
    return proc_manager.restart_server(folder)

# ===================== دوال مساعدة محسّنة ====================
def get_current_user():
    """الحصول على المستخدم الحالي من الجلسة"""
    if "username" in session:
        return db["users"].get(session["username"])
    return None

def get_user_servers_dir(username):
    """الحصول على مسار مجلد سيرفرات المستخدم"""
    path = os.path.join(USERS_DIR, username, "SERVERS")
    os.makedirs(path, exist_ok=True)
    return path

def is_admin(username):
    """التحقق من صلاحيات الأدمن"""
    if username == ADMIN_USERNAME:
        return True
    u = db["users"].get(username)
    return u.get("is_admin", False) if u else False

@lru_cache(maxsize=1)
def get_public_ip():
    """الحصول على IP العام مع تخزين مؤقت"""
    try:
        return requests.get('https://api.ipify.org', timeout=3).text
    except Exception:
        return "127.0.0.1"

def generate_api_key():
    """توليد مفتاح API آمن"""
    return secrets.token_urlsafe(32)

def get_user_by_api_key(api_key):
    """البحث عن مستخدم بواسطة API Key"""
    for username, udata in db["users"].items():
        if udata.get("api_key") == api_key:
            return username, udata
    return None, None

def uptime_str(start_time):
    """تحويل وقت البدء إلى نص مفهوم"""
    if not start_time:
        return "0 ثانية"
    diff = time.time() - start_time
    days = int(diff // 86400)
    hours = int((diff % 86400) // 3600)
    mins = int((diff % 3600) // 60)
    parts = []
    if days > 0: parts.append(f"{days} يوم")
    if hours > 0: parts.append(f"{hours} ساعة")
    if mins > 0: parts.append(f"{mins} دقيقة")
    return " و ".join(parts) if parts else "أقل من دقيقة"

def _check_admin_access():
    """التحقق من صلاحيات الأدمن (للـ API)"""
    if "username" in session and is_admin(session["username"]):
        return True
    
    # التحقق من API Key
    api_key = None
    if request.is_json:
        try:
            api_key = request.get_json().get("api_key")
        except Exception:
            pass
    if not api_key:
        api_key = request.args.get("api_key")
    
    if api_key:
        username, user = get_user_by_api_key(api_key)
        if username and is_admin(username):
            return True
    
    return False

def handle_errors(f):
    """ديكوريتور لمعالجة الأخطاء بشكل موحد"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            app.logger.error(f"خطأ في {f.__name__}: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "message": "حدث خطأ داخلي في الخادم"
            }), 500
    return decorated_function

# ===================== تنظيف الجلسات المنتهية ====================
def cleanup_expired_sessions():
    """تنظيف الجلسات المنتهية الصلاحية"""
    try:
        current_time = datetime.now()
        for username, user_data in list(db["users"].items()):
            if username == ADMIN_USERNAME:
                continue
            
            created_at = user_data.get("created_at")
            expiry_days = user_data.get("expiry_days", 365)
            
            if created_at:
                created_date = datetime.fromisoformat(created_at)
                if (current_time - created_date).days > expiry_days:
                    # انتهت صلاحية المستخدم
                    app.logger.info(f"انتهت صلاحية المستخدم {username}")
                    # يمكن إضافة إجراءات إضافية هنا
    except Exception as e:
        app.logger.error(f"خطأ في تنظيف الجلسات: {e}")

# ===================== الصفحات (متوافقة تماماً) ====================
@app.route('/')
def home():
    if 'username' not in session:
        return redirect('/login')
    if is_admin(session['username']):
        return redirect('/admin')
    return redirect('/dashboard')

@app.route('/login')
def login_page():
    if 'username' in session:
        return redirect('/')
    return send_from_directory(BASE_DIR, 'login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect('/login')
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/admin')
def admin_panel():
    if 'username' not in session or not is_admin(session['username']):
        return redirect('/login')
    return send_from_directory(BASE_DIR, 'admin_panel.html')

# ===================== API المصادقة (محسّنة) ====================
@app.route('/api/register', methods=['POST'])
@handle_errors
def api_register():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "بيانات غير صالحة"})
    
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    # التحقق من صحة البيانات
    if not username or not password:
        return jsonify({"success": False, "message": "جميع الحقول مطلوبة"})
    if len(username) < 3:
        return jsonify({"success": False, "message": "اسم المستخدم 3 أحرف على الأقل"})
    if len(password) < 4:
        return jsonify({"success": False, "message": "كلمة المرور 4 أحرف على الأقل"})
    if username in db["users"]:
        return jsonify({"success": False, "message": "اسم المستخدم موجود بالفعل"})
    if username == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "لا يمكن استخدام هذا الاسم"})
    
    # تسجيل مباشر بدون موافقة مسبقة
    db["users"][username] = {
        "password": hashlib.sha256(password.encode()).hexdigest(),
        "is_admin": False,
        "created_at": str(datetime.now()),
        "max_servers": db["plans"]["free"]["max_servers"],
        "expiry_days": 365,
        "last_login": None,
        "telegram_id": None,
        "api_key": None,
        "storage_limit": db["plans"]["free"]["storage"],
        "plan": "free"
    }
    save_db(db)
    
    # إنشاء مجلدات المستخدم
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "SERVERS"), exist_ok=True)
    
    # إشعار للأدمن
    notify_admin(
        f"🔔 *مستخدم جديد اشترك في NASSIM HOST!*\n"
        f"👤 المستخدم: `{username}`\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    
    return jsonify({
        "success": True,
        "message": f"✅ تم إنشاء حسابك بنجاح! يمكنك تسجيل الدخول الآن."
    })

@app.route('/api/login', methods=['POST'])
@handle_errors
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "بيانات غير صالحة"})
    
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    # تسجيل دخول الأدمن
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD_RAW:
        session.clear()
        session['username'] = username
        session.permanent = True
        db["users"][ADMIN_USERNAME]["last_login"] = str(datetime.now())
        save_db(db, immediate=True)
        return jsonify({"success": True, "redirect": "/admin", "is_admin": True})
    
    # تسجيل دخول المستخدمين العاديين
    user = db["users"].get(username)
    if user and user["password"] == hashlib.sha256(password.encode()).hexdigest():
        session.clear()
        session['username'] = username
        session.permanent = True
        user["last_login"] = str(datetime.now())
        save_db(db)
        return jsonify({"success": True, "redirect": "/dashboard", "is_admin": False})
    
    return jsonify({"success": False, "message": "بيانات غير صحيحة"})

@app.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    response = make_response(jsonify({"success": True}))
    response.set_cookie('session', '', expires=0)
    return response

@app.route('/api/current_user')
def api_current_user():
    if "username" in session:
        u = db["users"].get(session["username"])
        if u:
            return jsonify({
                "success": True,
                "username": session["username"],
                "is_admin": u.get("is_admin", False) or session["username"] == ADMIN_USERNAME,
                "plan": u.get("plan", "free")
            })
    return jsonify({"success": False})

# ===================== API Key (محسّنة) ====================
@app.route('/api/create_api_key', methods=['POST'])
@handle_errors
def create_api_key():
    if 'username' not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    
    username = session['username']
    new_key = generate_api_key()
    db["users"][username]["api_key"] = new_key
    save_db(db, immediate=True)
    
    return jsonify({
        "success": True,
        "api_key": new_key,
        "message": "تم إنشاء مفتاح API"
    })

@app.route('/api/link_telegram', methods=['POST'])
@handle_errors
def link_telegram():
    if 'username' not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    
    data = request.get_json()
    tg_id = str(data.get('telegram_id', ''))
    if not tg_id:
        return jsonify({"success": False, "message": "معرف تليجرام مطلوب"})
    
    db["users"][session['username']]["telegram_id"] = tg_id
    save_db(db, immediate=True)
    
    return jsonify({"success": True, "message": "تم ربط حساب التليجرام"})

# ===================== API الخطط ====================
@app.route('/api/plans')
def get_plans():
    plans = db.get("plans", {})
    return jsonify({"success": True, "plans": plans})

@app.route('/api/user/upgrade', methods=['POST'])
@handle_errors
def upgrade_plan():
    if 'username' not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    
    data = request.get_json()
    plan_id = data.get("plan_id")
    
    if not plan_id or plan_id not in db.get("plans", {}):
        return jsonify({"success": False, "message": "خطة غير موجودة"})
    
    plan = db["plans"][plan_id]
    username = session['username']
    user = db["users"][username]
    
    # تحديث خطة المستخدم
    user["plan"] = plan_id
    user["max_servers"] = plan["max_servers"]
    user["storage_limit"] = plan["storage"]
    
    save_db(db)
    
    # إشعار للأدمن
    notify_admin(
        f"💎 *ترقية خطة جديدة!*\n"
        f"👤 المستخدم: `{username}`\n"
        f"📦 الخطة: {plan['name']}\n"
        f"💰 السعر: {plan['price']}$"
    )
    
    return jsonify({
        "success": True,
        "message": f"✅ تم ترقية حسابك إلى {plan['name']}"
    })

# ===================== API الإدارة - المستخدمون ====================
@app.route('/api/admin/users')
def admin_users():
    if not _check_admin_access():
        return jsonify({"success": False}), 403
    
    users_list = []
    for uname, udata in db["users"].items():
        users_list.append({
            "username": uname,
            "is_admin": udata.get("is_admin", False),
            "created_at": udata.get("created_at"),
            "last_login": udata.get("last_login"),
            "max_servers": udata.get("max_servers", 1),
            "expiry_days": udata.get("expiry_days", 365),
            "telegram_id": udata.get("telegram_id"),
            "api_key": udata.get("api_key"),
            "plan": udata.get("plan", "free")
        })
    
    return jsonify({"success": True, "users": users_list})

@app.route('/api/admin/create-user', methods=['POST'])
@handle_errors
def admin_create_user():
    if not _check_admin_access():
        return jsonify({"success": False}), 403
    
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    max_servers = int(data.get("max_servers", 2))
    expiry_days = int(data.get("expiry_days", 365))
    
    if not username or not password:
        return jsonify({"success": False, "message": "جميع الحقول مطلوبة"})
    if username in db["users"]:
        return jsonify({"success": False, "message": "المستخدم موجود"})
    
    db["users"][username] = {
        "password": hashlib.sha256(password.encode()).hexdigest(),
        "is_admin": False,
        "created_at": str(datetime.now()),
        "max_servers": max_servers,
        "expiry_days": expiry_days,
        "last_login": None,
        "telegram_id": None,
        "api_key": None,
        "storage_limit": 512000,
        "plan": "free"
    }
    save_db(db, immediate=True)
    
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "SERVERS"), exist_ok=True)
    
    return jsonify({"success": True, "message": "✅ تم إنشاء الحساب"})

@app.route('/api/admin/delete-user', methods=['POST'])
@handle_errors
def admin_delete_user():
    if not _check_admin_access():
        return jsonify({"success": False}), 403
    
    data = request.get_json()
    username = data.get("username", "").strip()
    
    if not username or username == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "لا يمكن حذف هذا المستخدم"})
    
    if username in db["users"]:
        # حذف جميع سيرفرات المستخدم
        for fid in [fid for fid, srv in db["servers"].items() if srv["owner"] == username]:
            stop_server_process(fid)
            srv_path = db["servers"][fid]["path"]
            if os.path.exists(srv_path):
                shutil.rmtree(srv_path, ignore_errors=True)
            del db["servers"][fid]
        
        # حذف مجلد المستخدم
        user_dir = os.path.join(USERS_DIR, username)
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir, ignore_errors=True)
        
        # حذف من قاعدة البيانات
        del db["users"][username]
        save_db(db, immediate=True)
        
        return jsonify({"success": True, "message": f"🗑 تم حذف المستخدم {username}"})
    
    return jsonify({"success": False, "message": "المستخدم غير موجود"})

@app.route('/api/admin/update-user', methods=['POST'])
@handle_errors
def admin_update_user():
    if not _check_admin_access():
        return jsonify({"success": False}), 403
    
    data = request.get_json()
    username = data.get("username", "").strip()
    
    if username not in db["users"]:
        return jsonify({"success": False, "message": "المستخدم غير موجود"})
    
    u = db["users"][username]
    if "max_servers" in data:
        u["max_servers"] = int(data["max_servers"])
    if "expiry_days" in data:
        u["expiry_days"] = int(data["expiry_days"])
    if "is_admin" in data:
        u["is_admin"] = bool(data["is_admin"])
    if "storage_limit" in data:
        u["storage_limit"] = int(data["storage_limit"])
    
    save_db(db, immediate=True)
    return jsonify({"success": True, "message": f"✅ تم تحديث {username}"})

# ===================== API النظام (محسّنة) ====================
@app.route('/api/system/metrics')
def get_metrics():
    """الحصول على مقاييس النظام مع تخزين مؤقت"""
    cache_key = "system_metrics"
    cached = metrics_cache.get(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        metrics = {
            "cpu": psutil.cpu_percent(interval=0.1),
            "memory": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent
        }
        metrics_cache.set(cache_key, metrics)
        return jsonify(metrics)
    except Exception as e:
        app.logger.error(f"خطأ في قراءة المقاييس: {e}")
        return jsonify({"cpu": 0, "memory": 0, "disk": 0})

@app.route('/api/ping', methods=['GET', 'POST'])
def ping():
    return jsonify({"status": "pong", "timestamp": str(datetime.now())})

# ===================== السيرفرات (محسّنة) ====================
@app.route('/api/servers')
@handle_errors
def list_servers():
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    user_servers = []
    total_disk_used_mb = 0.0
    
    for folder, srv in db["servers"].items():
        if srv["owner"] == session["username"]:
            disk_used_mb = _calculate_disk_usage(srv["path"])
            total_disk_used_mb += disk_used_mb
            
            user_servers.append({
                "folder": folder,
                "title": srv["name"],
                "subtitle": f"سيرفر {srv.get('type', 'Python')}",
                "type": srv.get("type", "Python"),
                "startup_file": srv.get("startup_file", ""),
                "status": srv.get("status", "Stopped"),
                "uptime": uptime_str(srv.get("start_time")) if srv.get("status") == "Running" else "0 ثانية",
                "port": srv.get("port", "N/A"),
                "plan": srv.get("plan", "free"),
                "storage_limit": srv.get("storage_limit", 100),
                "ram_limit": srv.get("ram_limit", 256),
                "cpu_limit": srv.get("cpu_limit", 0.5),
                "disk_used": disk_used_mb
            })
    
    user = db["users"].get(session["username"], {})
    return jsonify({
        "success": True,
        "servers": user_servers,
        "stats": {
            "used": len(user_servers),
            "total": user.get("max_servers", 2),
            "expiry": user.get("expiry_days", 365),
            "disk_used": round(total_disk_used_mb, 2),
            "disk_total": user.get("storage_limit", 512000),
        }
    })

def _calculate_disk_usage(path):
    """حساب استخدام القرص مع تخزين مؤقت"""
    if not os.path.exists(path):
        return 0.0
    
    disk_used = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    disk_used += os.path.getsize(fp)
                except (OSError, IOError):
                    pass
    except Exception:
        pass
    
    return round(disk_used / (1024 * 1024), 2)

@app.route('/api/server/add', methods=['POST'])
@handle_errors
def add_server():
    if "username" not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    
    user = db["users"].get(session["username"])
    if not user:
        return jsonify({"success": False, "message": "مستخدم غير موجود"})
    
    # التحقق من الحد الأقصى للسيرفرات
    user_srv_count = len([s for s in db["servers"].values() if s["owner"] == session["username"]])
    if user_srv_count >= user.get("max_servers", 2):
        return jsonify({
            "success": False,
            "message": f"وصلت للحد الأقصى ({user.get('max_servers', 2)}) سيرفر."
        })
    
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "message": "الرجاء إدخال اسم للسيرفر"})
    
    server_type = data.get("server_type", "Python")
    if server_type not in ("Python", "Node.js"):
        server_type = "Python"
    
    plan_id = user.get("plan", "free")
    plan = db["plans"].get(plan_id, db["plans"]["free"])
    
    # إنشاء معرف فريد للسيرفر
    folder = f"{session['username']}_{re.sub(r'[^a-zA-Z0-9]', '', name)}_{int(time.time())}"
    path = os.path.join(get_user_servers_dir(session["username"]), folder)
    os.makedirs(path, exist_ok=True)
    
    assigned_port = get_assigned_port()
    
    db["servers"][folder] = {
        "name": name,
        "owner": session["username"],
        "path": path,
        "type": server_type,
        "status": "Stopped",
        "created_at": str(datetime.now()),
        "startup_file": "",
        "pid": None,
        "port": assigned_port,
        "plan": plan_id,
        "storage_limit": plan["storage"],
        "ram_limit": plan["ram"],
        "cpu_limit": plan["cpu"]
    }
    save_db(db, immediate=True)
    
    return jsonify({"success": True, "message": f"✅ تم إنشاء الخادم {name}"})

@app.route('/api/server/action/<folder>/<action>', methods=['POST'])
@handle_errors
def server_action(folder, action):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False, "message": "غير مصرح"})
    
    if action == "start":
        if srv.get("status") == "Running":
            return jsonify({"success": False, "message": "الخادم يعمل بالفعل"})
        ok, msg = start_server_process(folder)
        return jsonify({"success": ok, "message": msg})
    
    elif action == "stop":
        stop_server_process(folder)
        return jsonify({"success": True, "message": "🛑 تم الإيقاف"})
    
    elif action == "restart":
        restart_server(folder)
        return jsonify({"success": True, "message": "🔄 تم إعادة التشغيل"})
    
    elif action == "delete":
        stop_server_process(folder)
        if os.path.exists(srv["path"]):
            shutil.rmtree(srv["path"], ignore_errors=True)
        del db["servers"][folder]
        save_db(db, immediate=True)
        return jsonify({"success": True, "message": "🗑 تم الحذف"})
    
    return jsonify({"success": False})

@app.route('/api/server/stats/<folder>')
@handle_errors
def get_server_stats(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    status = srv.get("status", "Stopped")
    
    # قراءة السجلات
    logs = _read_log_file(os.path.join(srv["path"], "out.log"), 500)
    errors = _read_log_file(os.path.join(srv["path"], "errors.log"), 50)
    
    # معلومات الذاكرة
    mem_info = "0 MB"
    if srv.get("pid") and status == "Running":
        try:
            p = psutil.Process(srv["pid"])
            mem_info = f"{p.memory_info().rss / (1024*1024):.1f} MB"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return jsonify({
        "success": True,
        "status": status,
        "logs": logs,
        "errors": errors,
        "mem": mem_info,
        "uptime": uptime_str(srv.get("start_time")) if status == "Running" else "0 ثانية",
        "port": srv.get("port", "--"),
        "ip": get_public_ip(),
        "type": srv.get("type", "Python")
    })

def _read_log_file(log_path, max_lines):
    """قراءة ملف سجل مع حد أقصى للأسطر"""
    if not os.path.exists(log_path):
        return "لا توجد مخرجات بعد"
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            # قراءة من نهاية الملف للخلف (أسرع)
            f.seek(0, 2)  # الانتقال لنهاية الملف
            file_size = f.tell()
            
            if file_size == 0:
                return ""
            
            # قراءة آخر 100KB تقريباً
            chunk_size = min(file_size, 100 * 1024)
            f.seek(max(0, file_size - chunk_size))
            
            lines = f.read().split('\n')
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
            
            return '\n'.join(lines)
    except Exception:
        return "خطأ في قراءة السجل"

# ===================== الملفات (محسّنة) ====================
@app.route('/api/files/list/<folder>')
def list_server_files(folder):
    if "username" not in session:
        return jsonify([]), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify([])
    
    path = srv["path"]
    files = []
    
    try:
        for f in os.listdir(path):
            if f in ['out.log', 'server.log', 'meta.json', 'errors.log']:
                continue
            
            fpath = os.path.join(path, f)
            try:
                stat = os.stat(fpath)
                size_str = _format_file_size(stat.st_size)
                
                files.append({
                    "name": f,
                    "size": size_str,
                    "is_dir": os.path.isdir(fpath),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    "is_zip": f.lower().endswith('.zip')
                })
            except (OSError, IOError):
                continue
    except Exception as e:
        app.logger.error(f"خطأ في عرض الملفات: {e}")
    
    return jsonify(sorted(files, key=lambda x: (not x['is_dir'], x['name'].lower())))

def _format_file_size(size_bytes):
    """تنسيق حجم الملف"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.1f} KB"
    else:
        return f"{size_bytes/(1024*1024):.1f} MB"

@app.route('/api/files/content/<folder>/<path:filename>')
def get_file_content(folder, filename):
    if "username" not in session:
        return jsonify({"content": ""}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"content": ""})
    
    if '..' in filename:  # منع تجاوز المسار
        return jsonify({"content": ""})
    
    fpath = os.path.join(srv["path"], filename)
    if not os.path.exists(fpath) or os.path.isdir(fpath):
        return jsonify({"content": ""})
    
    try:
        # الحد من حجم الملفات النصية المقروءة
        if os.path.getsize(fpath) > 10 * 1024 * 1024:  # 10MB
            return jsonify({"content": "[ملف كبير جداً للعرض - استخدم التحميل]"})
        
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({"content": content})
    except UnicodeDecodeError:
        return jsonify({"content": "[ملف ثنائي]"})
    except Exception as e:
        app.logger.error(f"خطأ في قراءة الملف {filename}: {e}")
        return jsonify({"content": "[خطأ في قراءة الملف]"})

@app.route('/api/files/save/<folder>/<path:filename>', methods=['POST'])
@handle_errors
def save_file_content(folder, filename):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    if '..' in filename:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    
    data = request.get_json()
    fpath = os.path.join(srv["path"], filename)
    
    try:
        # كتابة آمنة للملف
        temp_path = fpath + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            content = data.get("content", "")
            if len(content) > 50 * 1024 * 1024:  # 50MB حد أقصى
                return jsonify({"success": False, "message": "الملف كبير جداً"})
            f.write(content)
        
        # استبدال الملف الأصلي (عملية ذرية)
        if os.name == 'posix':
            os.replace(temp_path, fpath)
        else:
            if os.path.exists(fpath):
                os.remove(fpath)
            os.rename(temp_path, fpath)
        
        return jsonify({"success": True, "message": "✅ تم الحفظ"})
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/files/upload/<folder>', methods=['POST'])
@handle_errors
def upload_files(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    if not os.path.exists(srv["path"]):
        os.makedirs(srv["path"], exist_ok=True)
    
    files = request.files.getlist('files[]')
    if not files:
        return jsonify({"success": False, "message": "لا توجد ملفات"})
    
    uploaded = 0
    errors_list = []
    server_type = srv.get("type", "Python")
    
    for f in files:
        try:
            if not f or not f.filename or '..' in f.filename:
                continue
            
            save_path = os.path.join(srv["path"], f.filename)
            
            # حفظ الملف
            f.save(save_path)
            uploaded += 1
            
        except Exception as e:
            errors_list.append(str(e))
    
    if uploaded > 0:
        # تشغيل تثبيت المكتبات في الخلفية
        log_path = os.path.join(srv["path"], "out.log")
        thread_pool.submit_task(
            _auto_install_after_upload,
            srv["path"], server_type, log_path
        )
        
        msg = f"✅ تم رفع {uploaded} ملف"
        if errors_list:
            msg += f" (⚠️ {len(errors_list)} تحذير)"
        return jsonify({"success": True, "message": msg, "warnings": errors_list})
    
    return jsonify({"success": False, "message": "فشل الرفع", "errors": errors_list})

def _auto_install_after_upload(srv_path: str, server_type: str, log_path: str):
    """تثبيت المكتبات تلقائياً بعد الرفع"""
    try:
        with open(log_path, "a", encoding='utf-8') as lf:
            auto_install_deps(srv_path, server_type, lf)
    except Exception:
        pass

@app.route('/api/files/rename/<folder>', methods=['POST'])
@handle_errors
def rename_file(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    data = request.get_json() or {}
    old_name = data.get("old_name", "").strip()
    new_name = data.get("new_name", "").strip()
    
    if not old_name or not new_name or '..' in old_name or '..' in new_name:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    
    old_path = os.path.join(srv["path"], old_name)
    new_path = os.path.join(srv["path"], new_name)
    
    if not os.path.exists(old_path):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    if os.path.exists(new_path):
        return jsonify({"success": False, "message": "يوجد ملف بهذا الاسم"})
    
    try:
        os.rename(old_path, new_path)
        
        # تحديث ملف التشغيل إذا لزم الأمر
        if srv.get("startup_file") == old_name:
            srv["startup_file"] = new_name
            save_db(db)
        
        return jsonify({
            "success": True,
            "message": f"✅ تمت إعادة التسمية إلى {new_name}"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/files/unzip/<folder>/<path:filename>', methods=['POST'])
@handle_errors
def unzip_file(folder, filename):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    if not filename.lower().endswith('.zip'):
        return jsonify({"success": False, "message": "الملف ليس zip"})
    
    zip_path = os.path.join(srv["path"], filename)
    if not os.path.exists(zip_path):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # فحص الملف قبل الفك
            bad = zf.testzip()
            if bad:
                return jsonify({"success": False, "message": f"ملف ZIP تالف: {bad}"})
            
            # منع فك ضغط ملفات كبيرة جداً
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > 500 * 1024 * 1024:  # 500MB
                return jsonify({"success": False, "message": "ملف ZIP كبير جداً"})
            
            zf.extractall(srv["path"])
        
        return jsonify({"success": True, "message": f"✅ تم فك ضغط {filename}"})
    except zipfile.BadZipFile:
        return jsonify({"success": False, "message": "ملف ZIP غير صالح"})
    except Exception as e:
        app.logger.error(f"خطأ في فك الضغط: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/files/delete/<folder>', methods=['POST'])
@handle_errors
def delete_files(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    data = request.get_json() or {}
    names = data.get("names", data.get("name", []))
    if isinstance(names, str):
        names = [names]
    
    deleted = 0
    for name in names:
        if not name or '..' in name:
            continue
        fpath = os.path.join(srv["path"], name)
        try:
            if os.path.isdir(fpath):
                shutil.rmtree(fpath)
            elif os.path.exists(fpath):
                os.remove(fpath)
            deleted += 1
        except Exception as e:
            app.logger.error(f"خطأ في حذف {name}: {e}")
    
    if deleted > 0:
        return jsonify({"success": True, "message": f"🗑 تم حذف {deleted} ملف"})
    return jsonify({"success": False, "message": "فشل الحذف"})

@app.route('/api/files/create/<folder>', methods=['POST'])
@handle_errors
def create_file_api(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    data = request.get_json()
    filename = data.get("filename", "").strip()
    if not filename or '..' in filename:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    
    fpath = os.path.join(srv["path"], filename)
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(data.get("content", ""))
        return jsonify({"success": True, "message": f"✅ تم إنشاء {filename}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/server/set-startup/<folder>', methods=['POST'])
@handle_errors
def set_startup_file(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    data = request.get_json()
    filename = data.get("filename", "").strip()
    
    if not filename or '..' in filename:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    
    if not os.path.exists(os.path.join(srv["path"], filename)):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    
    srv["startup_file"] = filename
    save_db(db, immediate=True)
    
    return jsonify({
        "success": True,
        "message": f"✅ تم تعيين {filename} كملف التشغيل"
    })

@app.route('/api/server/install/<folder>', methods=['POST'])
@handle_errors
def install_requirements(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False})
    
    server_type = srv.get("type", "Python")
    log_path = os.path.join(srv["path"], "out.log")
    
    if server_type == "Node.js":
        deps_file = os.path.join(srv["path"], "package.json")
        file_name = "package.json"
    else:
        deps_file = os.path.join(srv["path"], "requirements.txt")
        file_name = "requirements.txt"
    
    if not os.path.exists(deps_file):
        return jsonify({"success": False, "message": f"{file_name} غير موجود"})
    
    try:
        # بدء التثبيت في الخلفية
        thread_pool.submit_task(_run_install, srv["path"], server_type, log_path)
        return jsonify({
            "success": True,
            "message": f"📦 بدأ تثبيت {server_type} dependencies"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

def _run_install(srv_path, server_type, log_path):
    """تشغيل التثبيت في الخلفية"""
    try:
        with open(log_path, "a", encoding='utf-8') as lf:
            lf.write(f"\n{'='*50}\n📦 تثبيت ({server_type})...\n{'='*50}\n")
            auto_install_deps(srv_path, server_type, lf)
    except Exception as e:
        app.logger.error(f"خطأ في التثبيت: {e}")

# ===================== API البوت (محسّنة) ====================
@app.route('/api/bot/verify', methods=['POST'])
@handle_errors
def bot_verify():
    data = request.get_json()
    api_key = data.get('api_key', '').strip()
    
    if not api_key:
        return jsonify({"success": False, "message": "API Key مطلوب"})
    
    username, user = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"})
    
    return jsonify({
        "success": True,
        "username": username,
        "is_admin": is_admin(username),
        "max_servers": user.get("max_servers", 2),
        "expiry_days": user.get("expiry_days", 365)
    })

@app.route('/api/bot/servers', methods=['GET'])
def bot_list_servers():
    api_key = request.args.get('api_key')
    if not api_key:
        return jsonify({"success": False, "message": "API Key مطلوب"}), 401
    
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    user_servers = []
    for folder, srv in db["servers"].items():
        if srv["owner"] == username:
            user_servers.append({
                "folder": folder,
                "title": srv["name"],
                "status": srv.get("status", "Stopped"),
                "uptime": uptime_str(srv.get("start_time")) if srv.get("status") == "Running" else "0 ثانية",
                "port": srv.get("port", "N/A"),
                "plan": srv.get("plan", "free"),
                "type": srv.get("type", "Python"),
                "storage_limit": srv.get("storage_limit", 100),
                "ram_limit": srv.get("ram_limit", 256),
                "cpu_limit": srv.get("cpu_limit", 0.5)
            })
    
    return jsonify({"success": True, "servers": user_servers})

@app.route('/api/bot/server/action', methods=['POST'])
@handle_errors
def bot_server_action():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    action = data.get('action')
    
    if not all([api_key, folder, action]):
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    
    if action == "start":
        if srv.get("status") == "Running":
            return jsonify({"success": False, "message": "السيرفر يعمل بالفعل"})
        ok, msg = start_server_process(folder)
        return jsonify({"success": ok, "message": msg})
    
    elif action == "stop":
        stop_server_process(folder)
        return jsonify({"success": True, "message": "🛑 تم الإيقاف"})
    
    elif action == "restart":
        restart_server(folder)
        return jsonify({"success": True, "message": "🔄 تم إعادة التشغيل"})
    
    elif action == "delete":
        stop_server_process(folder)
        if os.path.exists(srv["path"]):
            shutil.rmtree(srv["path"], ignore_errors=True)
        del db["servers"][folder]
        save_db(db, immediate=True)
        return jsonify({"success": True, "message": "🗑 تم الحذف"})
    
    return jsonify({"success": False, "message": "إجراء غير معروف"})

@app.route('/api/bot/console', methods=['GET'])
def bot_console():
    api_key = request.args.get('api_key')
    folder = request.args.get('folder')
    
    if not api_key or not folder:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    
    logs = _read_log_file(os.path.join(srv["path"], "out.log"), 500)
    return jsonify({"success": True, "logs": logs})

@app.route('/api/bot/errors', methods=['GET'])
def bot_errors():
    api_key = request.args.get('api_key')
    folder = request.args.get('folder')
    
    if not api_key or not folder:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    
    errors = _read_log_file(os.path.join(srv["path"], "errors.log"), 300) or "✅ لا توجد أخطاء مسجلة"
    return jsonify({"success": True, "errors": errors})

@app.route('/api/bot/install', methods=['POST'])
@handle_errors
def bot_install():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    
    if not api_key or not folder:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    
    server_type = srv.get("type", "Python")
    log_path = os.path.join(srv["path"], "out.log")
    
    if server_type == "Node.js":
        if not os.path.exists(os.path.join(srv["path"], "package.json")):
            return jsonify({"success": False, "message": "package.json غير موجود"}), 404
    else:
        if not os.path.exists(os.path.join(srv["path"], "requirements.txt")):
            return jsonify({"success": False, "message": "requirements.txt غير موجود"}), 404
    
    try:
        thread_pool.submit_task(_run_install, srv["path"], server_type, log_path)
        return jsonify({
            "success": True,
            "message": f"📦 بدأ تثبيت {server_type} dependencies"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/create_server', methods=['POST'])
@handle_errors
def bot_create_server():
    data = request.get_json()
    api_key = data.get('api_key')
    name = data.get('name', '').strip()
    server_type = data.get('server_type', 'Python')
    
    if not api_key:
        return jsonify({"success": False, "message": "API Key مطلوب"}), 400
    if not name:
        return jsonify({"success": False, "message": "الرجاء إدخال اسم للسيرفر"}), 400
    
    username, user = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    user_srv_count = len([s for s in db["servers"].values() if s["owner"] == username])
    max_allowed = user.get("max_servers", 2)
    
    if user_srv_count >= max_allowed:
        return jsonify({
            "success": False,
            "message": f"وصلت للحد الأقصى ({max_allowed}) سيرفر"
        })
    
    if server_type not in ("Python", "Node.js"):
        server_type = "Python"
    
    plan_id = user.get("plan", "free")
    plan = db["plans"].get(plan_id, db["plans"]["free"])
    
    folder = f"{username}_{re.sub(r'[^a-zA-Z0-9]', '', name)}_{int(time.time())}"
    path = os.path.join(get_user_servers_dir(username), folder)
    os.makedirs(path, exist_ok=True)
    
    assigned_port = get_assigned_port()
    
    db["servers"][folder] = {
        "name": name,
        "owner": username,
        "path": path,
        "type": server_type,
        "status": "Stopped",
        "created_at": str(datetime.now()),
        "startup_file": "",
        "pid": None,
        "port": assigned_port,
        "plan": plan_id,
        "storage_limit": plan["storage"],
        "ram_limit": plan["ram"],
        "cpu_limit": plan["cpu"]
    }
    save_db(db, immediate=True)
    
    return jsonify({
        "success": True,
        "message": f"✅ تم إنشاء السيرفر {name}",
        "folder": folder,
        "port": assigned_port
    })

@app.route('/api/bot/set_startup', methods=['POST'])
@handle_errors
def bot_set_startup():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    filename = data.get('filename')
    
    if not all([api_key, folder, filename]):
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    
    file_path = os.path.join(srv["path"], filename)
    if not os.path.exists(file_path):
        return jsonify({"success": False, "message": "الملف غير موجود"}), 404
    
    srv["startup_file"] = filename
    save_db(db, immediate=True)
    
    return jsonify({
        "success": True,
        "message": f"✅ تم تعيين {filename} كملف التشغيل"
    })

# ===================== تشغيل التطبيق (محسّن) ====================
if __name__ == "__main__":
    # تنظيف الجلسات المنتهية عند البدء
    cleanup_expired_sessions()
    
    # بدء نظام المراقبة
    proc_manager._ensure_monitoring()
    
    # تشغيل التطبيق
    port = int(os.environ.get("PORT", 5000))
    
    try:
        # استخدام gunicorn في production إن أمكن
        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False  # منع إعادة التحميل التلقائي في production
        )
    except KeyboardInterrupt:
        app.logger.info("إيقاف التطبيق...")
    finally:
        # تنظيف الموارد
        proc_manager.cleanup_all()
        thread_pool.shutdown()
        db_manager._flush_writes()
        app.logger.info("تم إيقاف التطبيق وتنظيف الموارد")