# 🚀 NASSIM HOST - نظام استضافة السيرفرات

<div align="center">

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![Flask](https://img.shields.io/badge/flask-3.0-red)
![License](https://img.shields.io/badge/license-MIT-orange)
![Railway](https://img.shields.io/badge/deploy-Railway-purple)

**نظام استضافة متكامل لإدارة وتشغيل سيرفرات Python و Node.js**

[المميزات](#-المميزات) • [التثبيت](#-التثبيت) • [النشر](#-النشر-على-railway) • [الاستخدام](#-الاستخدام) • [API](#-api)

</div>

---

## 📋 المميزات

### 🎯 المميزات الأساسية
- ✅ **دعم Python و Node.js** - تشغيل سيرفرات متعددة اللغات
- ✅ **لوحة تحكم كاملة** - إدارة سهلة للسيرفرات
- ✅ **تثبيت تلقائي للمكتبات** - `requirements.txt` و `package.json`
- ✅ **مراقبة حية** - CPU، RAM، Disk Usage
- ✅ **نظام صلاحيات** - أدمن ومستخدمين عاديين
- ✅ **بوت تليجرام** - تحكم كامل عن بعد

### 🛡️ الأمان
- ✅ **تشفير كلمات المرور** - SHA-256
- ✅ **API Keys** - مصادقة آمنة للبوت
- ✅ **حماية من Path Traversal**
- ✅ **جلسات آمنة** - HttpOnly Cookies
- ✅ **حدود للموارد** - منع استنزاف الخادم

### ⚡ الأداء
- ✅ **تخزين مؤقت** - Caching للاستعلامات المتكررة
- ✅ **كتابة مجمعة** - Batching للـ Database
- ✅ **مراقبة ذكية** - إعادة تشغيل تلقائي
- ✅ **تنظيف Zombie Processes**
- ✅ **تدوير السجلات** - Log Rotation

### 📦 الخطط
| الخطة | التخزين | الرام | المعالج | السيرفرات | السعر |
|-------|---------|------|---------|-----------|-------|
| 🎁 مجاني | 500MB | 256MB | 0.5 Core | 2 | $0 |
| 💎 4GB | 4GB | 1GB | 1 Core | 5 | $5 |
| 💎 10GB | 10GB | 2GB | 2 Core | 10 | $10 |
| 💎 40GB | 40GB | 4GB | 4 Core | 20 | $25 |

---

## 📦 التثبيت

### المتطلبات
- Python 3.10+
- pip
- Node.js (اختياري - لتشغيل سيرفرات Node.js)

### التثبيت المحلي

```bash
# 1. استنساخ المشروع
git clone https://github.com/USERNAME/NASSIM-HOST.git
cd NASSIM-HOST

# 2. إنشاء بيئة افتراضية
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. تثبيت المكتبات
pip install -r requirements.txt

# 4. تشغيل التطبيق
python app.py
