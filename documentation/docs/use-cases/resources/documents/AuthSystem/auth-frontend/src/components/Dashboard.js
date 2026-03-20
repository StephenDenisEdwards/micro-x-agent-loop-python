import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import axios from 'axios';

function Dashboard() {
  const { user, logout } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const response = await axios.get('https://localhost:5001/api/users');
      setUsers(response.data);
      setError('');
    } catch (err) {
      setError('Failed to load users');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'Never';
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1>Dashboard</h1>
        <button onClick={logout} className="btn-logout">
          Logout
        </button>
      </div>

      <div className="user-info">
        <h2>Your Profile</h2>
        <div className="info-row">
          <span className="info-label">Name:</span>
          <span className="info-value">{user?.firstName} {user?.lastName}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Email:</span>
          <span className="info-value">{user?.email}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Member since:</span>
          <span className="info-value">{formatDate(user?.createdAt)}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Last login:</span>
          <span className="info-value">{formatDate(user?.lastLoginAt)}</span>
        </div>
      </div>

      <div className="users-list">
        <h2>All Users</h2>
        {loading ? (
          <p>Loading users...</p>
        ) : error ? (
          <p className="error-message">{error}</p>
        ) : (
          <div>
            {users.map((u) => (
              <div key={u.id} className="user-card">
                <h3>{u.firstName} {u.lastName}</h3>
                <p>Email: {u.email}</p>
                <p>Joined: {formatDate(u.createdAt)}</p>
                {u.lastLoginAt && <p>Last login: {formatDate(u.lastLoginAt)}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default Dashboard;
