import React, { useRef } from 'react';
import { Upload } from 'lucide-react';
import './FileUpload.css';

interface FileUploadProps {
    onFileLoaded: (data: any) => void;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onFileLoaded }) => {
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const json = JSON.parse(event.target?.result as string);
                onFileLoaded(json);
            } catch (err) {
                alert("JSON解析失败，请检查文件格式");
            }
        };
        reader.readAsText(file);
    };

    return (
        <div className="upload-container" onClick={() => fileInputRef.current?.click()}>
            <input
                type="file"
                accept=".json"
                ref={fileInputRef}
                onChange={handleFileChange}
                style={{ display: 'none' }}
            />
            <div className="upload-content">
                <Upload size={48} className="upload-icon" />
                <h3>点击或拖拽上传 Chat JSON</h3>
                <p>所有数据仅在本地浏览器处理，不会上传服务器</p>
            </div>
        </div>
    );
};
