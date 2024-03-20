Config_array={'Processor':{"variant01":"i5","variant02":"4thGen"},"RAM":{"variant01":"4GB","variant02":"DDR4"}}
#lap_def={'Processor':["variant01","variant02"],"RAM":["variant01"]}
part_mapping={'Processor':["variant01","variant02"],"RAM":["variant01","variant02"]}
#i5 4thGen - 4GB

class ItemConfig:
    def __init__(self,config,part_mapping):
        self.config=config
        self.part_mapping=part_mapping
        
    def get_part_config(self,type_data):
        data_list=[]
        for i in self.part_mapping[type_data]:
            data_list.append(self.config[type_data][i])
        return ' '.join(data_list)
    
    def get_item_code(self):
        item_code=[]
        for part in self.part_mapping:
            data=self.get_part_config(part)
            item_code.append(data)
        item_code_str=' - '.join(item_code)
        print(item_code_str)

a=ItemConfig(Config_array, part_mapping)
a.get_item_code()