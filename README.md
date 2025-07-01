# 🔉 MorseNet: Декодер аудио файлов с кодом морзе с помощью нейросетей

## 🔍 О проекте
MorseNet - это нейросетевая модель для автоматического декодирования аудио файлов с морзе в текст. Проект включает:
- Модель MorseNet на PyTorch
- FastAPI сервер для инференса
- Набор инструментов для обучения и тестирования

**Метрика качества:** Levenshtein mean - усредненное расстояние левенштейна между истинными сообщениями и сообщениями предсказанными моделью.
## 📂 Структура проекта
```
morse_decoder/
├── 📂notebooks/
│   ├── ...                 #Все неудачные попытки и чеклист исправлений
├── 📂src_dara/             
|   ├── 📂data_to_treaning/   # Данные что будут использоваться для тренировки моделей на сервере
|   ├── 📂saved_models/
|   |   ├── MorseNet.pth    # Базовая модель MorseNet
|   ├── 📂*morse_dataset/     # Базовый датасет на котором обучалась модель MorseNet  
|   |   ├── morse_dataset
|   |   ├── test.csv  
|   |   ├── train.csv  
├── 📂src_decoder/
|   ├── 📂ad-test?/           # Скрипты для AB-тестирования
|   ├── 📂configs/            
|   │   ├── ⚙️config.yaml     # Параметры для тестирования моделей
|   │   ├── ⚙️config.py       # Базовые значения параметров
│   ├── 📂data/                 
│   │   ├── dataset.py      # Класс Dataset
│   ├── 📂models/
│   │   ├── BaseModel.py    # Базовый класс моделей на сервере
│   │   ├── MorseNet.py     # Архитектура основной модели MorseNet
├── README.md
├── requirements.txt        
├── train.py                # FastAPI router to train and inference a new models
├── inference.py            # FastAPI router to MorseNet inference
├── 🚀main.py                 # Точка входа в FastAPI
```
