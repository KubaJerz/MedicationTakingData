import argparse
import os
from tqdm import tqdm
import warnings
import logging
import random



import torch
import torch.nn  as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torcheval.metrics.functional import multiclass_f1_score

from tensor_builder import getDataSet
from util_tl import save_metrics, plot_combined_metrics, check_and_save_best_model, train_prep

'''
IMPORTANT NOTES about this training script
-we expect the forward pass to return logits
-we pass logits into the criterion
'''

def train(model, train_loader, test_loader, criterion, optimizer, device, epochs, metrics, best_dev_f1, best_dev_loss, save_dir, train_id):
    model = model.to(device)
    best_dev_f1 = best_dev_f1
    best_dev_loss = best_dev_loss
    
    for epoch in tqdm(range(epochs), desc='Progress: '):
        model.train()
        epoch_loss = 0
        epoch_f1 = 0

        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device).squeeze() 
            
            optimizer.zero_grad()
            logits = model.forward(X_batch)
            
            loss = criterion(logits.flatten(), y_batch)
            f1 = multiclass_f1_score((torch.sigmoid(logits) > 0.5).long().flatten(), y_batch.long(), num_classes=model.num_classes,  average="macro").item()

            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            epoch_f1 += f1

        metrics['train_loss'].append(epoch_loss / len(train_loader))
        metrics['train_f1'].append(epoch_f1 / len(train_loader))

        # eval loop
        test_epoch_loss = 0
        test_epoch_f1 = 0

        with torch.no_grad():
            for X_batch, y_batch in test_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device).squeeze() 

                devlogits = model(X_batch)
                dev_loss = criterion(devlogits.flatten(), y_batch).item()
                dev_f1 = multiclass_f1_score((torch.sigmoid(devlogits) > 0.5).long().flatten(), y_batch.long(), num_classes=model.num_classes,  average="macro").item()
                
                test_epoch_loss += dev_loss
                test_epoch_f1 += dev_f1

        metrics['dev_loss'].append(test_epoch_loss / len(test_loader))
        metrics['dev_f1'].append(test_epoch_f1 / len(test_loader))

        best_dev_loss, best_dev_f1 = check_and_save_best_model(
            metrics=metrics, model=model, epoch=epoch, save_dir=save_dir, 
            train_id=train_id, best_dev_loss=best_dev_loss, best_dev_f1=best_dev_f1)

        if (epoch+1) % 2 == 0:
            plot_combined_metrics(metrics['train_loss'], metrics['dev_loss'], 
                                metrics['train_f1'], metrics['dev_f1'], metrics['best_f1_dev'], 
                                metrics['best_loss_dev'], train_id, save_dir)
            
    return metrics
 

def run_training(
    training_id,
    model_path,
    sub_dir,
    window_size,
    stride,
    train_percent=0.7,
    lr=0.01,
    random_state=69,
    train_batch_size=32,
    test_batch_size=-1,
    epochs=15,
    resume=False,
    full=False,
    f1=False,
    loss=False,
):

    # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # print(f"Using device: {device}")
    device = torch.device("cuda:1" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    print(f"Train percent: {train_percent}")
    print(f"Random state: {random_state}")
    print("Train Batch size: ","FULL" if train_batch_size == -1 else train_batch_size)
    print("Test Batch size: ", "FULL" if test_batch_size == -1 else test_batch_size)
    print("Epochs: ", epochs)


    model, metrics, save_dir, model_name = train_prep(
        model_input=model_path,
        resume=resume,
        f1=f1,
        full=full,
        loss=loss,
        training_id=training_id,
        sub_dir=sub_dir #this is only a vald value when training with the tw since it specifly where to save the sub models that were genorated
        )
    
    #Randomy pic a set of particant to train on 
    train_dataset, test_dataset = getDataSet(randomState=random_state, window_size=window_size, stride=stride, flatten=False)

    if train_batch_size == -1:
        train_batch_size = len(train_dataset)
    if test_batch_size == -1:
        test_batch_size = len(test_dataset)

    train_id = training_id

    train_loader = DataLoader(train_dataset, batch_size=train_batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=test_batch_size, shuffle=False)

    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(model.parameters(),lr=lr)

    warnings.filterwarnings("ignore", category=UserWarning, module="torchmetrics")
    logging.getLogger().setLevel(logging.ERROR)  # This will suppress WARNING level logs
    metrics = train(model=model, train_loader=train_loader, test_loader=test_loader, criterion=criterion, optimizer=optimizer, device=device, epochs=epochs, metrics=metrics, best_dev_f1=metrics['best_f1_dev'], best_dev_loss=metrics['best_loss_dev'], save_dir=save_dir, train_id=train_id)

    model_path = os.path.join(save_dir, f'{train_id}_Full.pth')
    torch.save(model, model_path)
    metrics_path = os.path.join(save_dir, f'{train_id}_Full_metrics.json')
    save_metrics(metrics, metrics_path)
    print(f"Training completed. Model saved as '{model_path}' and metrics saved as '{metrics_path}'.")

    return model, metrics


def main():
    parser = argparse.ArgumentParser(description="Basic train script")
    parser.add_argument("training_id", type=str, help="Training ID")
    parser.add_argument('--resume', '-r', action='store_true', help='if we are resuming training then path to model is and already init model')
    parser.add_argument("model_path", type=str, help="Path to the model")
    parser.add_argument("--train_percent", type=float, default=0.7, help="Percentage of data to use for training (default: 0.7)")
    parser.add_argument("--random_state", type=int, default=69, help="Random state for dataset split (default: 69)")
    parser.add_argument("--train_batch_size", "-trbs", type=int, required=True, help="Batch size for training (required), (-1) t do full batch")
    parser.add_argument("--test_batch_size", "-tebs",type=int, default=-1, help="Batch size for testing. If not present, uses full batch (-1)")    
    parser.add_argument("--epochs", type=int, default=15, help="Number of epochs (default: 15)")
    
    # Group to handle the resume options
    resume_group = parser.add_mutually_exclusive_group(required=False)
    resume_group.add_argument('-full', action='store_true', help='resume from the very end of the last models training')
    resume_group.add_argument('-f1', action='store_true', help='Resume from best F1 option of the model')
    resume_group.add_argument('-loss', action='store_true', help='Resume from best Loss option of the model')

    args = parser.parse_args()

    if args.resume and not (args.full or args.f1 or args.loss):
        parser.error("--resume/-r requires at least one of -full, -f1, or -loss")

    run_training(
        training_id=args.training_id,
        model_path=args.model_path,
        sub_dir=None,
        train_percent=args.train_percent,
        random_state=args.random_state,
        train_batch_size=args.train_batch_size,
        test_batch_size=args.test_batch_size,
        epochs=args.epochs,
        resume=args.resume,
        full=args.full,
        f1=args.f1,
        loss=args.loss
    )

if __name__ == "__main__":
    main()