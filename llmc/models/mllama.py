from loguru import logger
from PIL import Image
from transformers import (AutoConfig, AutoProcessor,
                          MllamaForConditionalGeneration)

from llmc.utils.registry_factory import MODEL_REGISTRY

from .llama import Llama


@MODEL_REGISTRY
class Mllama(Llama):
    def __init__(self, model_path, torch_dtype, device_map=None, use_cache=False):
        super().__init__(model_path, torch_dtype, device_map, use_cache)

    def build_model(self):
        self.vlm_model_config = AutoConfig.from_pretrained(
            self.model_path, trust_remote_code=True
        )
        if not self.use_cache:
            self.vlm_model_config.text_config.use_cache = False
        logger.info(f'self.vlm_model_config : {self.vlm_model_config}')
        self.vlm_model = MllamaForConditionalGeneration.from_pretrained(
            self.model_path,
            config=self.vlm_model_config,
            torch_dtype=self.torch_dtype,
            low_cpu_mem_usage=True,
        )
        self.vision_model = self.vlm_model.vision_model
        self.projector = self.vlm_model.multi_modal_projector
        self.model = self.vlm_model.language_model
        self.model_config = self.vlm_model_config.text_config
        self.need_update_mask = True

    def preprocess(self, img_qas):
        processor = AutoProcessor.from_pretrained(self.model_path)
        samples = []
        for idx in range(len(img_qas)):
            img_path = img_qas[idx]['img']
            image = [Image.open(img_path)]
            message = [
                {
                    'role': 'user',
                    'content': [
                        {'index': 0, 'type': 'image', 'text': None},
                        {'index': None, 'type': 'text', 'text': img_qas[idx]['question']}
                    ]
                }
            ]
            text = processor.apply_chat_template(message, tokenize=False)
            sample = processor(text=text, images=image, return_tensors='pt').to(next(self.vlm_model.parameters()).dtype) # noqa
            samples.append(sample)
        return samples

    def get_layernorms_in_block(self, block):
        return {
            'input_layernorm': block.input_layernorm,
            'post_attention_layernorm': block.post_attention_layernorm,
        }

    def get_subsets_in_block(self, block):
        if hasattr(block, 'cross_attn'):
            return [
                {
                    'layers': {'cross_attn.q_proj': block.cross_attn.q_proj},
                    'prev_op': [block.input_layernorm],
                    'input': ['cross_attn.q_proj'],
                    'inspect': block.cross_attn,
                    'has_kwargs': True,
                    'sub_keys': {
                        'cross_attention_states': 'cross_attention_states',
                        'attention_mask': 'cross_attention_mask',
                        'output_attentions': 'output_attentions',
                        'past_key_value': 'past_key_value',
                        'cache_position': 'cache_position',
                    }
                },
                {
                    'layers': {
                        'cross_attn.k_proj': block.cross_attn.k_proj,
                        'cross_attn.v_proj': block.cross_attn.v_proj,
                    },
                    'prev_op': [],
                    'input': ['cross_attn.k_proj'],
                    'inspect': block.cross_attn,
                    'has_kwargs': True,
                    'sub_keys': {
                        'cross_attention_states': 'cross_attention_states',
                        'attention_mask': 'cross_attention_mask',
                        'output_attentions': 'output_attentions',
                        'past_key_value': 'past_key_value',
                        'cache_position': 'cache_position',
                    }
                },
                {
                    'layers': {'cross_attn.o_proj': block.cross_attn.o_proj},
                    'prev_op': [block.cross_attn.v_proj],
                    'input': ['cross_attn.o_proj'],
                    'inspect': block.cross_attn.o_proj,
                    'has_kwargs': False,
                },
                {
                    'layers': {
                        'mlp.gate_proj': block.mlp.gate_proj,
                        'mlp.up_proj': block.mlp.up_proj,
                    },
                    'prev_op': [block.post_attention_layernorm],
                    'input': ['mlp.gate_proj'],
                    'inspect': block.mlp,
                    'has_kwargs': False,
                    'is_mlp': True,
                },
                {
                    'layers': {'mlp.down_proj': block.mlp.down_proj},
                    'prev_op': [block.mlp.up_proj],
                    'input': ['mlp.down_proj'],
                    'inspect': block.mlp.down_proj,
                    'has_kwargs': False,
                    'is_mlp': True,
                },
            ]
        return [
            {
                'layers': {
                    'self_attn.q_proj': block.self_attn.q_proj,
                    'self_attn.k_proj': block.self_attn.k_proj,
                    'self_attn.v_proj': block.self_attn.v_proj,
                },
                'prev_op': [block.input_layernorm],
                'input': ['self_attn.q_proj'],
                'inspect': block.self_attn,
                'has_kwargs': True,
            },
            {
                'layers': {'self_attn.o_proj': block.self_attn.o_proj},
                'prev_op': [block.self_attn.v_proj],
                'input': ['self_attn.o_proj'],
                'inspect': block.self_attn.o_proj,
                'has_kwargs': False,
            },
            {
                'layers': {
                    'mlp.gate_proj': block.mlp.gate_proj,
                    'mlp.up_proj': block.mlp.up_proj,
                },
                'prev_op': [block.post_attention_layernorm],
                'input': ['mlp.gate_proj'],
                'inspect': block.mlp,
                'has_kwargs': False,
                'is_mlp': True,
            },
            {
                'layers': {'mlp.down_proj': block.mlp.down_proj},
                'prev_op': [block.mlp.up_proj],
                'input': ['mlp.down_proj'],
                'inspect': block.mlp.down_proj,
                'has_kwargs': False,
                'is_mlp': True,
            },
        ]
