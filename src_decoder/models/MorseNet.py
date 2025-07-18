from pathlib import Path
import Levenshtein
import numpy as np
import datetime
import torch
import torch.nn as nn
import torch.optim as optim

import mlflow
import mlflow.pytorch

from typing import Union, Tuple, Dict
from src_decoder.configs.config import Config, setup_mlflow
from torch.utils.tensorboard import SummaryWriter
from src_decoder.models.BaseModel import BaseMLModel
from torch.utils.data import Dataset, DataLoader

class MorseNet(nn.Module,BaseMLModel):
    def __init__(self, config: Config, name_to_save=None, name_to_load="MorseNet"):
        super().__init__()
        """
        MorseNet model for Morse code recognition.
        
        Args:
            num_classes: Number of output classes (symbols)
            first_fe_count: Number of filters in first conv layer
            second_fe_count: Number of filters in second conv layer
            third_fe_count: Number of filters in third conv layer
            quad_fe_count: Number of filters in fourth conv layer
            kernel_size: Convolution kernel size
            padding: Convolution padding
            n_mels: Number of mel filters (input spectrogram height)
            gru_hidden: LSTM hidden size
            dropout: Dropout probability
            lr: Learning rate
            Blank: Blank from CTC loss
        """
        
        # ===== Init paramemers =====
        self.conf = config

        self.n_mels = self.conf.data.n_mels
        self.blank = self.conf.blank_char
        self.blank_ind = self.conf.blank_ind
        self.int_to_char = self.conf.int_to_char
        self.conf = self.conf.model

        self.lr = self.conf.lr
        
        self.name_to_save = name_to_save
        self.name_to_load = name_to_load
        # ===== CNN =====
        self.net_conv = nn.Sequential(
            nn.Conv2d(1, self.conf.first_fe_count, 
                      self.conf.kernel_size, 
                      stride=1, 
                      padding=self.conf.padding),
            nn.BatchNorm2d(self.conf.first_fe_count),
            nn.GELU(),
            nn.MaxPool2d((1, 2), (1, 2)),
            
            nn.Conv2d(self.conf.first_fe_count, 
                      self.conf.second_fe_count, 
                      self.conf.kernel_size, 
                      stride=1, 
                      padding=self.conf.padding),
            nn.BatchNorm2d(self.conf.second_fe_count),
            nn.GELU(),
            nn.MaxPool2d((2, 1), (2, 1)),
            
            nn.Conv2d(self.conf.second_fe_count, 
                      self.conf.third_fe_count, 
                      self.conf.kernel_size, 
                      stride=1, 
                      padding=self.conf.padding),
            nn.BatchNorm2d(self.conf.third_fe_count),
            nn.GELU(),
            nn.MaxPool2d((2, 2), (2, 2)),
            
            nn.Conv2d(self.conf.third_fe_count, 
                      self.conf.quad_fe_count, 
                      self.conf.kernel_size, 
                      stride=1, 
                      padding=self.conf.padding),
            nn.BatchNorm2d(self.conf.quad_fe_count),
            nn.GELU(),
            nn.MaxPool2d((2, 1), (2, 1))
        )
        
        # ===== Automatic CNN output =====
        with torch.no_grad():
            dummy_input = torch.randn(1, 1, self.n_mels, 356)
            cnn_out = self.net_conv(dummy_input)
            self.cnn_output_features = cnn_out.shape[1] * cnn_out.shape[2]

        # print(f"CNN размерность выхода: {cnn_out.shape}"); 
        # print(f"CNN число фичей: {self.cnn_output_features}")
        # ===== Projection before RNN =====

        self.layer1 = nn.Linear(self.cnn_output_features, self.n_mels*2); 
        self.gelu = nn.GELU()
        
        # ===== RNN =====
        self.rnn = nn.LSTM(
            input_size=self.n_mels * 2,
            hidden_size=self.conf.gru_hidden,
            num_layers=2,
            bidirectional=True,
            dropout=self.conf.dropout,
            batch_first=True
        )
        
        # ===== Classifier =====
        self.layer_norm = nn.LayerNorm(self.conf.gru_hidden * 2)      
        self.dropout = nn.Dropout(self.conf.dropout)   
        self.layer2 = nn.Linear(self.conf.gru_hidden * 2, self.conf.num_classes)  

        self._optimazer = optim.Adam(params=self.parameters(), lr=self.lr)
        self._scheduler = optim.lr_scheduler.ReduceLROnPlateau(self._optimazer, 
                                                               mode="min", 
                                                               factor=0.5, 
                                                               patience=3)
        self._loss_func = nn.CTCLoss(blank=self.blank_ind, 
                                     reduction="mean", 
                                     zero_infinity=True).to(self.device)

    def setup_learn(self, optimazer, scheduler, loss_func):
        """Setup castom optimazer, scheduler, loss funcion"""
        self._optimazer = optimazer
        self._scheduler = scheduler
        self._loss_func = loss_func

    def __ctc_decoder(self, logits, int_char_map, blank_label_idx) -> str:
        preds = []
        logits_cpu = logits.cpu()
        max_inds = torch.argmax(logits_cpu.detach(), dim=2).t().numpy()

        for ind in max_inds:
            merged_inds = []
            prev_idx = None
            for idx in ind:
                if idx != blank_label_idx and idx != prev_idx:
                    merged_inds.append(idx)
                prev_idx = idx
            text = "".join([int_char_map.get(i, "") for i in merged_inds])
            preds.append(text)

        return preds

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # ===== CNN =====
        x = self.net_conv(x)
        
        # ===== Prepare for RNN =====
        batch, channels, reduced_mels, reduced_time = x.shape
        x = x.permute(0, 3, 1, 2).reshape(batch, reduced_time, -1)
        x = x.reshape(batch, reduced_time, -1)
        
        # ==== Projection =====
        x = self.layer1(x)
        x = self.gelu(x)
        
        # ===== RNN =====
        self.rnn.flatten_parameters()
        x, _ = self.rnn(x)
        
        # ===== Classifier =====
        x = self.layer_norm(x)
        x = self.dropout(x)
        x = self.layer2(x)
        return nn.functional.log_softmax(x.permute(1, 0, 2), dim=2)

    def fit(self, thain_data: DataLoader, val_data: DataLoader):
        """Train the model"""
        self.to(self.device) 
        lst_loss_train = []
        lst_loss_val = []
        best_val_loss = 0
        setup_mlflow()
        mlflow.set_experiment(f"MorseNet Experiment_{self.name_to_save}")
        with mlflow.start_run():
            mlflow.log_params({
                "lr": self.lr,
                "dropout": self.conf.dropout,
                "cnn_first_fe_count": self.conf.first_fe_count,
                "cnn_second_fe_count": self.conf.second_fe_count,
                "cnn_third_fe_count": self.conf.third_fe_count,
                "cnn_quad_fe_count": self.conf.quad_fe_count,
                "gru_hidden": self.conf.gru_hidden,
                "num_classes": self.conf.num_classes
            })

            for epoch in range(self.conf.epochs):
                self.train()

                epoch_train_loss = 0.0
                train_predicts = []

                for batch_ind, batch in enumerate(thain_data):
                    mel_spec, targets, targets_lens, _ = batch

                    mel_spec = mel_spec.to(self.device)
                    targets = targets.to(self.device)
                    targets_lens = targets_lens.to(self.device)

                    #===== Counting the length of mel_spec to transfer to CTC loss =====
                    self._optimazer.zero_grad()
                    predict = self(mel_spec).to(self.device) # (N=batch,T,C)
                    N = predict.shape[1]
                    T = predict.shape[0]
                    predict_lengths = torch.full(size=(N,), fill_value=T, dtype=torch.long).to(self.device)

                    try:
                        loss = self._loss_func(predict, 
                                            targets, 
                                            predict_lengths, 
                                            targets_lens.reshape(N))
                    except RuntimeError as re:
                        print(str(re))
                        continue

                    if torch.isnan(loss) or torch.isinf(loss): 
                        print(f"\nWarning: In batch-{batch_ind} loss train is NaN/Inf: {loss.item()}"); 
                        self._optimazer.zero_grad(); 
                        continue

                    loss.backward()
                    nn.utils.clip_grad_norm_(self.parameters(), max_norm=1.0)
                    self._optimazer.step()

                    epoch_train_loss += loss.item()

                train_loss = epoch_train_loss / len(thain_data)

                # ======== Validation ========
                self.eval()
                val_loss = 0.0
                total_val = 0
                val_predicts = []

                with torch.no_grad():
                    for batch_ind, batch in enumerate(val_data):
                        val_mel_spec, val_labels, val_label_lensin, _ = batch
                        val_mel_spec = val_mel_spec.to(self.device)
                        val_labels = val_labels.to(self.device)
                        val_label_lensin = val_label_lensin.to(self.device)
    
                        val_predict = self(val_mel_spec)

                        val_N = val_predict.shape[1]
                        val_T = val_predict.shape[0]
                        predict_val_lengths = torch.full(size=(val_N,), 
                                                        fill_value=val_T, 
                                                        dtype=torch.long)
                        val_loss += self._loss_func(val_predict, 
                                                    val_labels, 
                                                    predict_val_lengths, 
                                                    val_label_lensin).item()

                total_val = val_loss / len(val_data)

                lst_loss_train.append(train_loss)
                lst_loss_val.append(total_val)

                self._scheduler.step(total_val)
            
                #===== Information about gradients =====
                grad_norms = [param.grad.norm().item() 
                            for param in self.parameters() 
                            if param.grad is not None]

                #===== Information about the training step and loss data =====
                current_lr = self._optimazer.param_groups[0]["lr"]
                if current_lr <= 1e-6:
                    print("The learning rate has reached a minimum of 1e-6, the training has stopped")
                    break

                # Log to Mlflow
                mlflow.log_metric("Mean grad norm", np.mean(grad_norms), step=epoch)
                mlflow.log_metric("Max grad norm", np.max(grad_norms), step=epoch)
                mlflow.log_metric("Mean grad norm", np.min(grad_norms), step=epoch)
                mlflow.log_metric("Train_loss", train_loss, step=epoch)
                mlflow.log_metric("Val_loss", total_val, step=epoch)
                mlflow.log_metric("Learning_rate", current_lr, step=epoch)

            # ===== Save the trained model =====
            if self.name_to_save is not None:
                self.save(save_name=self.name_to_save)
                mlflow.pytorch.log_model(self, name=self.name_to_save)

    def fit_inference(self, 
                      test_data: DataLoader, 
                      val_data: DataLoader, 
                      name_to_load: str) -> Dict[str, list]:
        self.load_state_dict(torch.load(name_to_load))
        self.to(self.device) 
        self.eval()

        with torch.no_grad():
            train_mess = []
            train_predicts = []
            for loader in test_data:
                seq, test_target, _, mess = loader
                train_mess.extend(mess)

                logits = self(seq)
                predicted_values = self.__ctc_decoder(logits, 
                                                     self.int_to_char, 
                                                     self.blank_ind)
                train_predicts.extend(predicted_values)

            val_mess = []
            val_predicts = []
            for loader in val_data:
                seq, test_target, _, mess = loader
                val_mess.extend(mess)

                logits= self(seq)
                predicted_values = self.__ctc_decoder(logits, 
                                                     self.int_to_char, 
                                                     self.blank_ind)
                val_predicts.extend(predicted_values)

        mean_acc_test = np.mean([Levenshtein.ratio(test_pred, train_mess[ind]) 
                                 for ind, test_pred in enumerate(train_predicts)])
        mean_acc_val = np.mean([Levenshtein.ratio(val_pred, val_mess[ind]) 
                                for ind, val_pred in enumerate(val_predicts)])

        out = {"test": mean_acc_test,
               "valid": mean_acc_val
               }
        return out

    def predict(self, data: DataLoader) -> str:
        """Make prediction for audiofile"""
        with torch.no_grad():
            seq, _, _, _ = next(iter(data))
            logits = self(seq)
            predict = self.__ctc_decoder(logits, 
                                        self.int_to_char, 
                                        self.blank_ind)
        return predict

    def name(self):
        return self.name_to_save
    
    def save(self, save_name: str) -> None:
        """Save model state dict"""
        current_date = datetime.now()
        formatted_date = current_date.strftime("%d.%m.%y")
        save_patch = f"src_data/saved_models/{save_name}_{formatted_date}.pth"
        torch.save(self.state_dict(), save_patch)

    def load(self, name="MorseNet"):
        """Loading madel by name"""
        pt = f"src_data/saved_models/{name}.pth"
        self.load_state_dict(torch.load(pt))
