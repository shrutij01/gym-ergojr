import math
import pybullet as p
import time
import pybullet_data
import numpy as np

from gym_ergojr import get_scene
from gym_ergojr.utils.urdf_helper import URDF

MAX_VEL = 18  # not measured, but looks about right
MAX_FORCE = 1  # idk, seems to work
MOTOR_DIRECTIONS = [1, -1, -1, 1, -1, -1]  # how do the motors turn on real robot


class AbstractRobot():

    def __init__(self, debug=False, frequency=100, backlash=None):
        self.debug = debug
        self.frequency = frequency
        self.backlash = backlash
        if debug:
            p.connect(p.GUI)  # or p.DIRECT for non-graphical version
            p.resetDebugVisualizerCamera(cameraDistance=0.7,
                                         cameraYaw=135,
                                         cameraPitch=-45,
                                         cameraTargetPosition=[0, 0, 0])
        else:
            p.connect(p.DIRECT)

        p.setAdditionalSearchPath(pybullet_data.getDataPath())  # optional for ground

        self.robots = []
        self.motor_ids = [3, 4, 6, 8, 10, 12]  # this is consistent across different robots

    def addModel(self, robot_model, pose=None):
        if pose is None:
            pose = [0, 0, 0, 0, 0, 0]
        startPos = pose[:3]  # RGB = xyz
        startOrientation = p.getQuaternionFromEuler(pose[3:])  # rotated around which axis? # np.deg2rad(90)
        # rotating a standing cylinder around the y axis, puts it flat onto the x axis

        xml_path = get_scene(robot_model)
        robot_file = URDF(xml_path, force_recompile=True).get_path()
        robot_id = p.loadURDF(robot_file, startPos, startOrientation, useFixedBase=1)
        self.robots.append(robot_id)

        if self.debug:
            print(robot_model)
            for i in range(p.getNumJoints(robot_id)):
                print(p.getJointInfo(robot_id, i))

        return robot_id

    def load_backlash(self, robot_id, backlashes):
        for bl in backlashes:
            assert len(bl) == 3

            cid = p.createConstraint(robot_id, bl[0], robot_id, bl[1], p.JOINT_FIXED,
                                      jointAxis=[1, 0, 0],
                                      parentFramePosition=[0, 0, 0],
                                      childFramePosition=[0, 0, 0])
            p.changeConstraint(cid, [0, 0, 0.1], maxForce=bl[2])


    def clip_action(self, actions):
        return np.multiply(
            np.pi / 2 * np.clip(actions, -1, 1),
            MOTOR_DIRECTIONS
        )

    ## DEPRECATED
    # def act(self, actions, robot_id):
    #     actions_clipped = self.clip_action(actions)
    #     p.setJointMotorControlArray(self.robots[robot_id], self.motor_ids,
    #                                 p.POSITION_CONTROL,
    #                                 targetPositions=actions_clipped,
    #                                 forces=[MAX_FORCE] * 6)

    def act2(self, actions, robot_id):
        actions_clipped = self.clip_action(actions)
        for idx, act in enumerate(actions_clipped):
            p.setJointMotorControl2(self.robots[robot_id], self.motor_ids[idx],
                                    p.POSITION_CONTROL,
                                    targetPosition=act,
                                    force=MAX_FORCE,
                                    maxVelocity=MAX_VEL)

    def observe(self, robot_id):
        obs = p.getJointStates(self.robots[robot_id], self.motor_ids)
        pos = [x[0] for x in obs]
        vel = [x[1] for x in obs]
        return self.normalize(np.array(pos + vel))

    def normalize(self, posvel):
        assert len(posvel) == 12
        pos_norm = (posvel[:6] + np.pi / 2) / np.pi
        vel_norm = (posvel[6:] + MAX_VEL) / (MAX_VEL * 2)
        posvel_norm = np.hstack((pos_norm, vel_norm))
        posvel_shifted = posvel_norm * 2 - 1
        posvel_shifted[:6] = np.multiply(posvel_shifted[:6], MOTOR_DIRECTIONS)

        return posvel_shifted

    def normalize_orn(self, orn):
        orn_norm = (np.array(orn) + np.pi / 2) / np.pi
        orn_shifted = orn_norm * 2 - 1
        return orn_shifted

    def close(self):
        p.disconnect()

    def step(self):
        p.stepSimulation()

    def set(self, posvel, robot_id):
        # !IMPORTANT set != act2... if you want the robot to stay in place
        # you also have to call act2 to set the target position

        assert len(posvel) == 12
        posvel_clipped = np.array(np.clip(posvel, -1, 1)).astype(np.float64)
        posvel_clipped[:6] *= np.pi / 2
        posvel_clipped[:6] = np.multiply(posvel_clipped[:6], MOTOR_DIRECTIONS)

        for i in range(6):
            p.resetJointState(
                self.robots[robot_id],
                self.motor_ids[i],
                targetValue=posvel_clipped[i],
                targetVelocity=posvel_clipped[i + 6]
            )

    def get_hits(self, robot1=0, robot2=1, links=None):
        if robot1 is None:
            hits = p.getContactPoints()

        elif robot2 is None:
            hits = p.getContactPoints(robot1)

        # links=(14,14) for sword+shield
        elif links is None:
            hits = p.getContactPoints(robot1, robot2)
        else:
            assert len(links) == 2
            hits = p.getContactPoints(robot1, robot2, links[0], links[1])
        return hits

    def rest(self):
        for i in range(len(self.robots)):
            self.set([0] * 12, i)

    def get_tip(self, robot_id):
        tip = 13  # TODO: might wanna check this in multi-robot setups
        state = p.getLinkState(self.robots[robot_id], tip)
        pos = state[0]
        orn = self.normalize_orn(p.getEulerFromQuaternion(state[1]))
        return (pos, orn)

    def hard_reset(self):
        p.resetSimulation()
        p.setGravity(0, 0, -10)
        p.setTimeStep(1 / self.frequency)
        p.setRealTimeSimulation(0)
        p.loadURDF("plane.urdf")
