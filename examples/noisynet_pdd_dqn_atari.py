from __future__ import division
import argparse
from PIL import Image
import numpy as np
import gym

from keras.models import Model
from keras.layers import Flatten, Convolution2D, Input
from keras.optimizers import Adam
import keras.backend as K
from rl.agents.dqn import DQNAgent
from rl.policy import GreedyQPolicy
from rl.memory import PrioritizedMemory
from rl.core import Processor
from rl.callbacks import FileLogger, ModelIntervalCheckpoint
from rl.layers import NoisyNetDense


INPUT_SHAPE = (84, 84)
WINDOW_LENGTH = 4

class AtariProcessor(Processor):
    def process_observation(self, observation):
        assert observation.ndim == 3  # (height, width, channel)
        img = Image.fromarray(observation)
        img = img.resize(INPUT_SHAPE).convert('L')  # resize and convert to grayscale
        processed_observation = np.array(img)
        assert processed_observation.shape == INPUT_SHAPE
        return processed_observation.astype('uint8')  # saves storage in experience memory

    def process_state_batch(self, batch):
        # We could perform this processing step in `process_observation`. In this case, however,
        # we would need to store a `float32` array instead, which is 4x more memory intensive than
        # an `uint8` array. This matters if we store 1M observations.
        processed_batch = batch.astype('float32') / 255.
        return processed_batch

    def process_reward(self, reward):
        return np.clip(reward, -1., 1.)

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['train', 'test'], default='train')
parser.add_argument('--env-name', type=str, default='RoadRunner-v0')
parser.add_argument('--weights', type=str, default=None)
args = parser.parse_args()

# Get the environment and extract the number of actions.
env = gym.make(args.env_name)
np.random.seed(123)
env.seed(123)
nb_actions = env.action_space.n

# Next, we build our model. We use the same model that was described by Mnih et al. (2015).
input_shape = (WINDOW_LENGTH, INPUT_SHAPE[0], INPUT_SHAPE[1])
frame = Input(shape=(input_shape))
cv1 = Convolution2D(32, kernel_size=(8,8), strides=4, activation='relu', data_format='channels_first')(frame)
cv2 = Convolution2D(64, kernel_size=(4,4), strides=2, activation='relu', data_format='channels_first')(cv1)
cv3 = Convolution2D(64, kernel_size=(3,3), strides=1, activation='relu', data_format='channels_first')(cv2)
dense= Flatten()(cv3)
dense = NoisyNetDense(512, activation='relu')(dense)
buttons = NoisyNetDense(nb_actions, activation='linear')(dense)
model = Model(inputs=frame,outputs=buttons)
print(model.summary())


memory = PrioritizedMemory(limit=1000000, alpha=.6, start_beta=.4, end_beta=1., steps_annealed=8000000, window_length=WINDOW_LENGTH)

processor = AtariProcessor()

policy = GreedyQPolicy()

dqn = DQNAgent(model=model, nb_actions=nb_actions, policy=policy, memory=memory,
               processor=processor, enable_double_dqn=True, enable_dueling_network=True, nb_steps_warmup=3000, gamma=.99, target_model_update=10000,
               train_interval=4, delta_clip=1.)

dqn.compile(Adam(lr=.00025/4), metrics=['mae'])

if args.mode == 'train':
    # Okay, now it's time to learn something! We capture the interrupt exception so that training
    # can be prematurely aborted. Notice that you can the built-in Keras callbacks!
    weights_filename = 'noisynet_pdd_dqn_{}_weights.h5f'.format(args.env_name)
    checkpoint_weights_filename = 'noisynet_pdd_dqn_' + args.env_name + '_weights_{step}.h5f'
    log_filename = 'dqn_{}_log.json'.format(args.env_name)
    callbacks = [ModelIntervalCheckpoint(checkpoint_weights_filename, interval=250000)]
    callbacks += [FileLogger(log_filename, interval=100)]
    dqn.fit(env, callbacks=callbacks, nb_steps=10000000, log_interval=10000)

    # After training is done, we save the final weights one more time.
    dqn.save_weights(weights_filename, overwrite=True)

elif args.mode == 'test':
    weights_filename = 'noiseynet_pdd_dqn_{}_weights.h5f'.format(args.env_name)
    if args.weights:
        weights_filename = args.weights
    dqn.load_weights(weights_filename)
    dqn.test(env, nb_episodes=10, visualize=True)
