import json
import os.path

import gurobipy as gp
import pandas as pd
from PIL import ImageDraw, Image
from gurobipy import GRB

ROUND_ID = 2
DAY_ID = 5
DATA_PATH = "data"


def read_burritos_data(roundId: int, dayId: int):
    folder = os.path.join(DATA_PATH, f"round{roundId}", f"day{dayId}")

    filemap = dict(
        demand_nodes=f"round{roundId}-day{dayId}_demand_node_data.csv",
        demand_trucks=f"round{roundId}-day{dayId}_demand_truck_data.csv",
        problem=f"round{roundId}-day{dayId}_problem_data.csv",
        truck_nodes=f"round{roundId}-day{dayId}_truck_node_data.csv")
    return {key: pd.read_csv(os.path.join(folder, filename)) for key, filename in filemap.items()}, folder


def render_trucks(trucks, folder):
    X_SHIFT = 0
    Y_SHIFT = 0

    X_SCALE = 1.42
    Y_SCALE = X_SCALE

    MARKER_TRUCK_COLOR = (255, 0, 0)
    MARKER_TRUCK_SIZE = 6

    MARKER_DEMAND_COLOR = (0, 255, 0)
    MARKER_DEMAND_SIZE = 5

    LINE_COLOR = (50, 50, 50)
    LINE_SIZE = 3

    source_image_path = os.path.join(folder, 'gurobiville.png')
    destination_image_path = os.path.join(folder, 'gurobiville-with-solution.png')
    # Open the image
    img = Image.open(source_image_path)

    # Create a drawing context
    draw = ImageDraw.Draw(img)

    # Add markers at specified positions
    for truck in trucks:
        x, y = truck['x'] * X_SCALE + X_SHIFT, truck['y'] * Y_SCALE + Y_SHIFT
        draw.rectangle([x - MARKER_TRUCK_SIZE, y - MARKER_TRUCK_SIZE, x + MARKER_TRUCK_SIZE, y + MARKER_TRUCK_SIZE],
                       fill=MARKER_TRUCK_COLOR)
        for customer in truck['customers']:
            x_cust, y_cust = customer['x'] * X_SCALE + X_SHIFT, customer['y'] * Y_SCALE + Y_SHIFT
            end_pos = x, y
            draw.line([(x_cust, y_cust), end_pos], fill=LINE_COLOR, width=LINE_SIZE)
            draw.rectangle([x_cust - MARKER_TRUCK_SIZE, y_cust - MARKER_TRUCK_SIZE, x_cust + MARKER_TRUCK_SIZE,
                            y_cust + MARKER_DEMAND_SIZE],
                           fill=MARKER_DEMAND_COLOR)

    # Save the modified image
    img.save(destination_image_path)

    # Display the modified image
    # img.show()
    img.close()


if __name__ == '__main__':
    connection_params = {
        # For Compute Server you need at least this
        #       "ComputeServer": "<server name>",
        #       "UserName": "<user name>",
        #       "ServerPassword": "<password>",
        # For Cluster Manager you need at least this
        #       "CSManager": "<manager name>",
        #       "CSAPIAccessID": "<access ID>",
        #       "CSAPISecret": "<secret>",
        # For Instant cloud you need at least this
        #       "CloudAccessID": "<access id>",
        #       "CloudSecretKey": "<secret>",
    }
    with gp.Env(params=connection_params) as env:
        with gp.Model("burritos", env=env) as model:

            print("\n\nGurobi Burritos game\n")
            data, folder = read_burritos_data(ROUND_ID, DAY_ID)

            # Constants
            problem = data['problem'].to_dict(orient="Records")[0]
            burrito_price = problem['burrito_price']
            ingredient_cost = problem['ingredient_cost']
            truck_cost = problem['truck_cost']

            truck_nodes = {node['index']: node for node in data['truck_nodes'].to_dict(orient="Records")}
            demand_nodes = {node['index']: node for node in data['demand_nodes'].to_dict(orient="Records")}
            demand_trucks = {(link['demand_node_index'], link['truck_node_index']): link for link in
                             data['demand_trucks'].to_dict(orient="Records") if link['scaled_demand'] > 0}

            # Decision variables
            truck_nodes_active = model.addVars(truck_nodes.keys(), vtype=GRB.BINARY, name='truck_node')
            demand_nearest_truck = model.addVars(demand_trucks.keys(), vtype=GRB.BINARY, name='demand_node')

            # Contraints

            # only at most one truck can be the closest to a customer building
            for demand_node_index in demand_nodes.keys():
                model.addConstr((sum(demand_nearest_truck[demand_node_index, truck_node_index] * truck_nodes_active[truck_node_index]
                                     for demand_node_index2,truck_node_index in demand_trucks.keys()
                                     if demand_node_index2==demand_node_index) <= 1.0),name = f"{demand_node_index}_nearest_truck")
            # the
            ## 1. Demand in a building is controoled by nearest track
            """for demand_node_index in demand_nodes.keys():
                activated_demand = model.addVar(lb=0, ub=demand_nodes[demand_node_index]['demand'],
                                                name=f"{demand_node_index}_activated_demand")
                demand_nodes[demand_node_index]['activated_demand'] = activated_demand
                activatable_demands = []
                for truck_node_index in truck_nodes.keys():
                    activatable_demand = model.addVar(lb=0, ub=demand_nodes[demand_node_index]['demand'],
                                                      name=f"{demand_node_index}_{truck_node_index}_activatable_demand")
                    model.addConstr(
                        activatable_demand == demand_trucks[demand_node_index, truck_node_index]['scaled_demand'] *
                        truck_nodes_active[truck_node_index],
                        name=f"{demand_node_index}_{truck_node_index}_activatable_demand_constraint")
                    activatable_demands.append(activatable_demand)
                model.update()
                model.addConstr((activated_demand == max_(activatable_demands)),
                                name=f"{demand_node_index}_activated_demand_constraint")"""

            # burritos sold
            burritos_sold = sum(demand_nearest_truck[demand_node_index, truck_node_index] * link['scaled_demand'] * truck_nodes_active[truck_node_index]  for
                                (demand_node_index, truck_node_index), link in demand_trucks.items())

            # set objective
            sales = burritos_sold * burrito_price
            ingredients = burritos_sold * ingredient_cost
            truck_cost = truck_nodes_active.sum() * truck_cost
            model.setObjective(sales - ingredients - truck_cost, GRB.MAXIMIZE)
            model.update()
            print(f"variables = {len(model.getVars())}\nContraints={len(model.getConstrs())}")
            # optimize
            model.optimize()

            # show the result
            print()
            print("*" * 100)
            print("Place Trucks in nodes:")
            solution_trucks = []
            for truck_index, truck_variable in truck_nodes_active.items():
                if truck_variable.X:
                    truck_node = truck_nodes[truck_index]
                    truck_node['customers'] = []
                    for (demand_node_index, truck_node_index2), nearest in demand_nearest_truck.items():
                        if truck_node_index2 != truck_index:
                            continue
                        if not nearest.X:
                            continue
                        customer = demand_nodes[demand_node_index]
                        customer['x'] = demand_nodes[demand_node_index]['x']
                        customer['y'] = demand_nodes[demand_node_index]['y']
                        truck_node['customers'].append(customer)
                    solution_trucks.append(truck_node)

            solution_trucks = sorted(solution_trucks, key=lambda x: x['x'] + x['y'])
            for truck_node in solution_trucks:
                print(f"\t{truck_node['index'].upper()} @({truck_node['x']:,.0f}, {truck_node['y']:,.0f})")

            # pprint(truck_nodes)
            render_trucks(solution_trucks, folder=folder)
            sol = json.loads(model.getJSONSolution())
            profit = sol['SolutionInfo']['ObjVal']
            print(f"Profit: {profit:,}")
