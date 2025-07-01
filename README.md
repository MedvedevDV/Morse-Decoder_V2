# 🔉 MorseNet: Декодер аудио файлов с кодом морзе с помощью нейросетей

## 🔍 О проекте
MorseNet — это нейросетевая модель для автоматического декодирования аудиофайлов с морзе в текст. Проект включает:
- Модель MorseNet на PyTorch
- FastAPI-сервер для инференса
- Набор инструментов для обучения и тестирования.

**Метрика качества:** Levenshtein mean - усредненное расстояние левенштейна между истинными сообщениями и сообщениями предсказанными моделью.
## 📂 Структура проекта
```
morse_decoder/
├── 📂notebooks/ #Все неудачные попытки и чеклист исправлений
│   ├── ...                   
├── 📂src_dara/             
|   ├── 📂data_to_treaning/   # Данные что будут использоваться для тренировки моделей на сервере
|   ├── 📂saved_models/
|   |   ├── MorseNet.pth       # Базовая модель MorseNet
|   ├── 📂*morse_dataset/     # Базовый датасет на котором обучалась модель MorseNet (создается пользователем)
|   |   ├── morse_dataset
|   |   ├── test.csv  
|   |   ├── train.csv  
├── 📂src_decoder/
|   ├── 📂ad-test?/           # Скрипты для AB-тестирования
|   ├── 📂configs/            
|   │   ├── ⚙️config.yaml     # Параметры для тестирования моделей
|   │   ├── ⚙️config.py       # Базовые значения параметров
│   ├── 📂data/                 
│   │   ├── dataset.py        # Класс Dataset
│   ├── 📂models/
│   │   ├── BaseModel.py      # Базовый класс моделей на сервере
│   │   ├── MorseNet.py       # Архитектура основной модели MorseNet
├── README.md
├── requirements.txt        
├── train.py                   # FastAPI router to train and inference a new models
├── inference.py               # FastAPI router to MorseNet inference
├── 🚀main.py                  # Точка входа в FastAPI
```
## 🧠 MorseNet: Как это работает
### 🏠 Архитектура модели
MorseNet использует гибридную архитектуру:
1. **CNN-блок** (4 слоя) для извлекает признаки из спектрограмм  
   `[batch, time(sequence), channels, mels]`
2. **Linear1 + GELU слои** преобразует пространство признаков CNN в пространство пригодное для LSTM  
   `[batch, time, channels, mels]` → `[batch, time, channels*mels]` → `[batch, time, N_MELS*2]`
3. **LSTM-блок** (2 слоя) для анализа временных зависимостей
   → `[batch, time, N_MELS*2]`
4. **LayerNorm + Dropout(0.5) слои** используются для борьбы с переобучением. _Для RNN сетей Dropout больше чем обычно!_
5. **Linear2** переводит размерность вектора к размерности пригодной для классификации  
   `[batch, time, N_MELS*2]` → `[batch, time, num_classes]`
6. **log_softmax** формирует из полученых значений логиты для функии потерь
   `[batch, time, num_classes]` → `[time/T,batch/N,num_classes/C]`

### 📈 Настройка обучения модели
| Компонент               | Описание                       | Ресурсы |
|-------------------------|--------------------------------|--------|
| **Adam**                |Оптимизатор    | [Adam](https://docs.pytorch.org/docs/stable/generated/torch.optim.Adam.html#torch.optim.Adam) |
| **ReduceLROnPlateau**   | Метод уменьшения шага обучения | [ReduceLROnPlateau](https://pytorch.org/docs/stable/optim.html#torch.optim.lr_scheduler.ReduceLROnPlateau) |
| **CTC**  | Функция потерь| [CTC architectures](https://huggingface.co/learn/audio-course/en/chapter3/ctc)   · [CTC loss](https://github.com/shouxieai/CTC_loss_pytorch?tab=readme-ov-file) |
```
  # Функция потерь
  self._loss_func = nn.CTCLoss(
      blank=self.blank,         # Индекс blank-символа (для CTC)
      reduction='mean',         # Усреднение потерь по батчу
      zero_infinity=True        # Стабилизация вычислений для длинных последовательностей
  ).to(self.device)            # Перенос на GPU (если доступно)
```
### Ключевые особенности
- Обработка аудио через Mel-спектрограммы
- Аугментация данных (Time/Frequency Masking)
- Поддержка русского алфавита и цифр
