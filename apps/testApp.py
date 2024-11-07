import appdaemon.plugins.hass.hassapi as hass
import threading
import json
import asyncio
import time
import Shared.convert as convert

class TestApp(hass.Hass):
    # Define a coroutine that simulates a long-running operation
    def initialize(self):
        self.log('Start TestApp1')
        #asyncio.run(self.main())
        #self.test()
        self.log('Start TestApp2')
        
    async def long_operation(self, message, delay):
        self.log(message)
        await asyncio.sleep(delay)  # Pause for delay seconds
        self.log(f"Done after {delay} seconds")
    
    # Define an async main function that creates and awaits two tasks
    async def main(self):
        self.log("In Main")
        # Get the current time
        start = time.perf_counter()

        # Create two tasks from the coroutines
        task1 = asyncio.create_task(self.long_operation("Task 1 started", 3))
        task2 = asyncio.create_task(self.long_operation("Task 2 started", 2))
    
        # Wait for the tasks to finish and get their results
        #result1 = await task1
        #result2 = await task2
    
        # Print the results and the elapsed time
        #print(result1)
        #print(result2)
        end = time.perf_counter()
        self.log(f"Finished in {end - start:.2f} seconds {task1} {task2}")
        await task2
        self.log(f"{task1} {task2}")

    def test(self):
        notifyCriterias = self.args['notify_criteria']

        for criteria in notifyCriterias:
            d = convert.listToDictionary(criteria)
            self.log(f'{d}')
                
            # list_of_dictionaries = [json.loads(json_string) for json_string in criteria]
            # # Convert the list of dictionaries into a dictionary with names as keys
            # dictionary_of_dictionaries = {d['name']: d for d in list_of_dictionaries}
            # print("List of Dictionaries:")
            # print(list_of_dictionaries)
            # print("\nDictionary of Dictionaries:")
            # print(dictionary_of_dictionaries)
            